#!/usr/bin/env python3
"""Read-only validator for production Clerk values in the environment manifest."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from env.manifest import Manifest, ManifestError, effective_var, load_manifest  # noqa: E402

DEFAULT_AUTHORIZED_PARTY = "https://app.altcontext.com"
APP_PORTAL_TARGET = "app-portal-build"
BACKEND_TARGET = "svc-vm"
JWKS_PATH = "/.well-known/jwks.json"
CHECK_TIMEOUT_S = 2.0
CHECK_MAX_BYTES = 256 * 1024
CHECK_READ_CHUNK = 4096
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)
_DEV_HOST_SUFFIXES = (".accounts.dev", ".lcl.dev", ".lclclerk.com")


class ClerkConfigError(Exception):
    """Manifest validation failure with no configuration values in the message."""


@dataclass(frozen=True, slots=True)
class DerivedClerkConfig:
    publishable_key: str
    frontend_api: str
    issuer: str
    jwks_url: str
    audience: str
    authorized_parties: tuple[str, ...]


def decode_publishable_key(raw: str) -> str:
    """Return the Clerk FAPI hostname encoded in a ``pk_live_`` key."""
    key = _single_line_value(raw)
    if key.startswith("pk_test_"):
        raise ClerkConfigError("development key refused; production requires pk_live_")
    if not key.startswith("pk_live_"):
        raise ClerkConfigError("key must start with pk_live_")
    payload = key.removeprefix("pk_live_")
    if not payload:
        raise ClerkConfigError("key is missing the encoded frontend API host")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
    except (ValueError, binascii.Error):
        try:
            decoded = base64.urlsafe_b64decode(padded)
        except (ValueError, binascii.Error) as exc:
            raise ClerkConfigError("key is not valid base64") from exc
    try:
        text = decoded.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ClerkConfigError("decoded host is not ASCII") from exc
    if not text.endswith("$"):
        raise ClerkConfigError("decoded host must end with '$'")
    host = text[:-1]
    if not host or "/" in host or ":" in host or "@" in host or " " in host:
        raise ClerkConfigError("malformed frontend API host")
    lowered = host.lower()
    if lowered == "localhost" or any(lowered.endswith(suffix) for suffix in _DEV_HOST_SUFFIXES):
        raise ClerkConfigError("development frontend API host refused")
    if not _HOSTNAME_RE.fullmatch(host):
        raise ClerkConfigError("malformed frontend API host")
    return host


def load_production_config(manifest_root: Path) -> DerivedClerkConfig:
    try:
        manifest = load_manifest(manifest_root)
    except (ManifestError, OSError, ValueError):
        raise ClerkConfigError("config/env manifest is invalid") from None

    publishable_key = _manifest_value(manifest, APP_PORTAL_TARGET, "VITE_CLERK_PUBLISHABLE_KEY")
    try:
        host = decode_publishable_key(publishable_key)
    except ClerkConfigError as exc:
        raise ClerkConfigError(f"VITE_CLERK_PUBLISHABLE_KEY: {exc}") from None

    frontend_api = f"https://{host}"
    fapi_value = _manifest_value(manifest, APP_PORTAL_TARGET, "VITE_CLERK_FAPI")
    if _https_origin(fapi_value, "VITE_CLERK_FAPI") != frontend_api:
        raise ClerkConfigError("VITE_CLERK_FAPI: must match the host encoded in VITE_CLERK_PUBLISHABLE_KEY")

    issuer = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_ISSUER")
    if issuer != frontend_api:
        raise ClerkConfigError("ACX_CLERK_ISSUER: must match VITE_CLERK_PUBLISHABLE_KEY")

    jwks_url = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_JWKS_URL")
    expected_jwks_url = f"{frontend_api}{JWKS_PATH}"
    if jwks_url != expected_jwks_url:
        raise ClerkConfigError("ACX_CLERK_JWKS_URL: must match ACX_CLERK_ISSUER")

    audience = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_AUDIENCE")
    if not audience or any(char in audience for char in "\n\r\0,"):
        raise ClerkConfigError("ACX_CLERK_AUDIENCE: one non-empty value is required")

    parties_raw = _manifest_value(manifest, BACKEND_TARGET, "ACX_CLERK_AUTHORIZED_PARTIES")
    parties = tuple(part.strip() for part in parties_raw.split(",") if part.strip())
    if parties != (DEFAULT_AUTHORIZED_PARTY,):
        raise ClerkConfigError("ACX_CLERK_AUTHORIZED_PARTIES: must contain only https://app.altcontext.com")

    return DerivedClerkConfig(
        publishable_key=publishable_key,
        frontend_api=frontend_api,
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience,
        authorized_parties=parties,
    )


def _manifest_value(manifest: Manifest, target_name: str, name: str) -> str:
    target = manifest.targets.get(target_name)
    if target is None or "prod" not in target.envs:
        raise ClerkConfigError(f"{name}: production target is unavailable")
    variable = next((item for item in manifest.vars if item.name == name), None)
    if variable is None or target_name not in variable.targets:
        raise ClerkConfigError(f"{name}: production manifest value is unavailable")
    value = effective_var(manifest, variable, target_name).values.get("prod")
    if not isinstance(value, str) or not value.strip():
        raise ClerkConfigError(f"{name}: production manifest value is required")
    return value.strip()


def _https_origin(raw: str, name: str) -> str:
    try:
        parsed = urlparse(raw)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.netloc)
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid = False
    if not valid:
        raise ClerkConfigError(f"{name}: exact https origin is required")
    return f"https://{parsed.netloc}"


def _single_line_value(raw: str) -> str:
    if "\0" in raw:
        raise ClerkConfigError("value contains a NUL")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1 or any(char in lines[0] for char in " \t"):
        raise ClerkConfigError("value must be a single line without whitespace")
    return lines[0]


def validate_frontend_modules(config: DerivedClerkConfig, module_paths: Sequence[Path]) -> None:
    if not module_paths:
        raise ClerkConfigError("reachable JavaScript module assets are required")
    has_key = False
    has_fapi = False
    for path in module_paths:
        try:
            contents = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise ClerkConfigError("reachable JavaScript module asset cannot be read") from None
        key_tokens = re.findall(r"\bpk_(?:live|test)_[A-Za-z0-9_+/=-]+", contents)
        if any(token != config.publishable_key for token in key_tokens):
            raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY: reachable module contains a different Clerk key")
        has_key = has_key or config.publishable_key in contents
        has_fapi = has_fapi or config.frontend_api in contents
    if not has_key:
        raise ClerkConfigError("VITE_CLERK_PUBLISHABLE_KEY is absent from reachable JavaScript modules")
    if not has_fapi:
        raise ClerkConfigError("VITE_CLERK_FAPI is absent from reachable JavaScript modules")


def fetch_jwks(
    url: str,
    *,
    timeout_s: float = CHECK_TIMEOUT_S,
    clock: Callable[[], float] | None = None,
) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ClerkConfigError("JWKS URL must be https")
    request = Request(
        url, method="GET", headers={"Accept": "application/json", "User-Agent": "acx-configure-clerk-production"}
    )
    now = time.monotonic if clock is None else clock
    deadline = now() + timeout_s
    remaining = deadline - now()
    if remaining <= 0:
        raise ClerkConfigError("JWKS check exceeded timeout")
    try:
        with urlopen(request, timeout=remaining) as response:  # noqa: S310 — scheme pinned to https above
            raw = _read_jwks_body(response, max_bytes=CHECK_MAX_BYTES, deadline=deadline, clock=now)
    except HTTPError as exc:
        raise ClerkConfigError(f"JWKS check HTTP {exc.code}") from exc
    except ClerkConfigError:
        raise
    except TimeoutError as exc:
        raise ClerkConfigError("JWKS check exceeded timeout") from exc
    except (URLError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            raise ClerkConfigError("JWKS check exceeded timeout") from exc
        raise ClerkConfigError("JWKS check failed") from exc
    if len(raw) > CHECK_MAX_BYTES:
        raise ClerkConfigError("JWKS response exceeded bounded size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClerkConfigError("JWKS response is not JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list) or not payload["keys"]:
        raise ClerkConfigError("JWKS response is missing keys")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="configure_clerk_production",
        description="Validate production Clerk settings from the environment manifest.",
    )
    parser.add_argument(
        "--root", type=Path, default=_REPO_ROOT / "config" / "env", help="environment manifest root"
    )
    parser.add_argument("--check", action="store_true", help="opt in to a bounded HTTPS JWKS check")
    parser.add_argument(
        "--verify-assets",
        action="store_true",
        help="read reachable JavaScript module paths from stdin and verify the production build values",
    )
    return parser


def execute(
    args: argparse.Namespace,
    *,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    jwks_get: Callable[[str], dict[str, object]] | None = None,
) -> int:
    stdin = sys.stdin if stdin is None else stdin
    stderr = sys.stderr if stderr is None else stderr
    try:
        config = load_production_config(args.root)
        if args.verify_assets:
            paths = [Path(line) for line in stdin.read().splitlines() if line]
            validate_frontend_modules(config, paths)
        if args.check:
            (fetch_jwks if jwks_get is None else jwks_get)(config.jwks_url)
        return 0
    except ClerkConfigError as exc:
        stderr.write(f"error: {exc}\n")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return execute(args)


def _read_jwks_body(
    response: object,
    *,
    max_bytes: int,
    deadline: float,
    clock: Callable[[], float],
    chunk_size: int = CHECK_READ_CHUNK,
) -> bytes:
    buf = bytearray()
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise ClerkConfigError("JWKS check exceeded timeout")
        _apply_socket_timeout(response, remaining)
        to_read = min(chunk_size, max_bytes + 1 - len(buf))
        if to_read <= 0:
            break
        try:
            chunk = response.read(to_read)  # type: ignore[attr-defined]
        except TimeoutError as exc:
            raise ClerkConfigError("JWKS check exceeded timeout") from exc
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise ClerkConfigError("JWKS response is not JSON")
        buf.extend(chunk)
        if len(buf) > max_bytes:
            break
    return bytes(buf)


def _apply_socket_timeout(response: object, timeout_s: float) -> None:
    bounded = max(timeout_s, 0.001)
    targets: list[object] = [response]
    fp = getattr(response, "fp", None)
    if fp is not None:
        targets.append(fp)
        raw = getattr(fp, "raw", None)
        if raw is not None:
            targets.append(raw)
            sock = getattr(raw, "_sock", None)
            if sock is not None:
                targets.append(sock)
    for target in targets:
        setter = getattr(target, "settimeout", None)
        if not callable(setter):
            continue
        try:
            setter(bounded)
        except (OSError, TypeError, ValueError):
            continue


if __name__ == "__main__":
    sys.exit(main())
