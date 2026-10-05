#!/usr/bin/env python3
"""Bootstrap production Clerk environment files for app.altcontext.com.

Stdlib CLI. Dry-run by default; writes only with ``--apply``. Secrets are
accepted from the environment, a protected file, or a prompt — never argv.
Each destination file is replaced atomically at mode 0600.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_AUTHORIZED_PARTY = "https://app.altcontext.com"
PUBLISHABLE_ENV = "CLERK_PUBLISHABLE_KEY"
SECRET_ENV = "CLERK_SECRET_KEY"
BACKEND_MANAGED_KEYS = (
    "ACX_CLERK_ISSUER",
    "ACX_CLERK_JWKS_URL",
    "ACX_CLERK_AUDIENCE",
    "ACX_CLERK_AUTHORIZED_PARTIES",
)
FRONTEND_MANAGED_KEYS = (
    "VITE_CLERK_PUBLISHABLE_KEY",
    "VITE_CLERK_FAPI",
)
SECRET_BACKEND_KEY = "CLERK_SECRET_KEY"
FRONTEND_FORBIDDEN_KEYS = frozenset({SECRET_BACKEND_KEY})
_SECRET_VALUE_PREFIXES = ("sk_live_", "sk_test_")
MANAGED_COMMENT = "# Clerk production portal auth (managed by configure_clerk_production.py)"
JWKS_PATH = "/.well-known/jwks.json"
CHECK_TIMEOUT_S = 2.0
CHECK_MAX_BYTES = 256 * 1024
CHECK_READ_CHUNK = 4096
_HOSTNAME_RE = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)
_ASSIGNMENT_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_DEV_HOST_SUFFIXES = (".accounts.dev", ".lcl.dev", ".lclclerk.com")
_REDACT_PREFIXES = ("pk_live_", "pk_test_", "sk_live_", "sk_test_")


class ClerkConfigError(Exception):
    """Operator-visible configuration or I/O failure without secret values."""


@dataclass(frozen=True, slots=True)
class DerivedClerkConfig:
    publishable_key: str
    secret_key: str | None
    frontend_api_host: str
    issuer: str
    jwks_url: str
    audience: str
    authorized_parties: tuple[str, ...]

    def backend_updates(self) -> dict[str, str]:
        updates = {
            "ACX_CLERK_ISSUER": self.issuer,
            "ACX_CLERK_JWKS_URL": self.jwks_url,
            "ACX_CLERK_AUDIENCE": self.audience,
            "ACX_CLERK_AUTHORIZED_PARTIES": ",".join(self.authorized_parties),
        }
        if self.secret_key is not None:
            updates[SECRET_BACKEND_KEY] = self.secret_key
        return updates

    def frontend_updates(self) -> dict[str, str]:
        return {
            "VITE_CLERK_PUBLISHABLE_KEY": self.publishable_key,
            "VITE_CLERK_FAPI": self.issuer,
        }


def redact(value: str) -> str:
    stripped = value.strip()
    for prefix in _REDACT_PREFIXES:
        if stripped.startswith(prefix):
            return f"{prefix}<redacted>"
    return stripped


def decode_publishable_key(raw: str) -> str:
    """Return the Clerk FAPI hostname encoded in a ``pk_live_`` key."""
    key = _single_line_secret(raw, name="publishable key")
    if key.startswith("pk_test_"):
        raise ClerkConfigError("refusing development publishable key (pk_test_); production requires pk_live_")
    if not key.startswith("pk_live_"):
        raise ClerkConfigError("publishable key must start with pk_live_")
    payload = key.removeprefix("pk_live_")
    if not payload:
        raise ClerkConfigError("publishable key is missing the encoded frontend API host")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
    except (ValueError, binascii.Error):
        try:
            decoded = base64.urlsafe_b64decode(padded)
        except (ValueError, binascii.Error) as exc:
            raise ClerkConfigError("publishable key is not valid base64") from exc
    try:
        text = decoded.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ClerkConfigError("publishable key decoded host is not ASCII") from exc
    if not text.endswith("$"):
        raise ClerkConfigError("publishable key decoded host must end with '$'")
    host = text[:-1]
    if not host or "/" in host or ":" in host or "@" in host or " " in host:
        raise ClerkConfigError("malformed Clerk frontend API host in publishable key")
    lowered = host.lower()
    if lowered == "localhost" or any(lowered.endswith(suffix) for suffix in _DEV_HOST_SUFFIXES):
        raise ClerkConfigError("refusing development frontend API host; production requires a live custom domain")
    if not _HOSTNAME_RE.fullmatch(host):
        raise ClerkConfigError("malformed Clerk frontend API host in publishable key")
    return host


def validate_secret_key(raw: str) -> str:
    key = _single_line_secret(raw, name="secret key")
    if key.startswith("sk_test_"):
        raise ClerkConfigError("refusing development secret key (sk_test_); production requires sk_live_")
    if not key.startswith("sk_live_"):
        raise ClerkConfigError("secret key must start with sk_live_")
    if len(key) < 16:
        raise ClerkConfigError("secret key is truncated")
    return key


def validate_audience(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ClerkConfigError("audience is required (session token template must set aud)")
    if any(ch in value for ch in "\n\r\0,"):
        raise ClerkConfigError("audience must be a single value without commas or newlines")
    return value


def validate_authorized_party(raw: str) -> str:
    value = raw.strip()
    if any(ch in value for ch in "\n\r\0"):
        raise ClerkConfigError("authorized party contains a newline")
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ClerkConfigError("authorized party must be an exact https origin (default https://app.altcontext.com)")
    return f"https://{parsed.netloc}"


def derived_config(
    *,
    publishable_key: str,
    audience: str,
    authorized_parties: Sequence[str],
    secret_key: str | None = None,
) -> DerivedClerkConfig:
    host = decode_publishable_key(publishable_key)
    parties = tuple(validate_authorized_party(item) for item in authorized_parties)
    if not parties:
        raise ClerkConfigError("at least one authorized party is required")
    secret = validate_secret_key(secret_key) if secret_key is not None else None
    issuer = f"https://{host}"
    return DerivedClerkConfig(
        publishable_key=_single_line_secret(publishable_key, name="publishable key"),
        secret_key=secret,
        frontend_api_host=host,
        issuer=issuer,
        jwks_url=f"{issuer}{JWKS_PATH}",
        audience=validate_audience(audience),
        authorized_parties=parties,
    )


def load_protected_value(path: Path, *, kind: str, require_owner_only: bool) -> str:
    _assert_safe_file(path, must_exist=True, require_owner_only=require_owner_only)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClerkConfigError(f"cannot read {kind} file") from exc
    return _single_line_secret(text, name=kind)


def parse_env_lines(text: str) -> list[str]:
    return text.splitlines()


def assignment_index(lines: Sequence[str]) -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT_RE.match(stripped)
        if match is None:
            continue
        key, raw_value = match.group(1), match.group(2)
        value = _unquote_env_value(raw_value)
        found.setdefault(key, []).append((index, value))
    return found


def reject_duplicate_assignments(found: Mapping[str, list[tuple[int, str]]]) -> None:
    for key, occurrences in found.items():
        if len(occurrences) < 2:
            continue
        values = {item[1] for item in occurrences}
        if len(values) > 1:
            raise ClerkConfigError(f"contradictory duplicate env var {key}")
        raise ClerkConfigError(f"duplicate env var {key}")


def reject_frontend_secret_boundary(existing: str, planned: str) -> None:
    """Refuse frontend env that contains backend-only secret keys or values.

    Validation is input+output and happens before any destination write. Error
    text names keys only — never secret values (RES-01, DATA-03).
    """
    for text in (existing, planned):
        found = assignment_index(parse_env_lines(text))
        reject_duplicate_assignments(found)
        for key, occurrences in found.items():
            if key in FRONTEND_FORBIDDEN_KEYS:
                raise ClerkConfigError(f"refusing frontend env: {key} is backend-only")
            for _index, value in occurrences:
                if value.startswith(_SECRET_VALUE_PREFIXES):
                    raise ClerkConfigError(f"refusing frontend env: backend-only secret material in {key}")


def merge_env_updates(existing: str, updates: Mapping[str, str]) -> str:
    for key, value in updates.items():
        _reject_unsafe_env_value(key, value)
    lines = parse_env_lines(existing)
    found = assignment_index(lines)
    reject_duplicate_assignments(found)
    pending = dict(updates)
    for key, occurrences in found.items():
        if key not in pending:
            continue
        index, _current = occurrences[0]
        lines[index] = f"{key}={_format_env_value(pending.pop(key))}"
    if pending:
        if lines and lines[-1].strip():
            lines.append("")
        if MANAGED_COMMENT not in (line.strip() for line in lines):
            lines.append(MANAGED_COMMENT)
        for key in _ordered_keys(pending):
            lines.append(f"{key}={_format_env_value(pending[key])}")
    body = "\n".join(lines)
    return body + "\n" if body else ""


def atomic_write_text(path: Path, content: str) -> None:
    _assert_safe_destination(path)
    try:
        original_stat = path.stat()
    except FileNotFoundError:
        original_stat = None
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(directory))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            if original_stat is not None:
                os.fchown(handle.fileno(), original_stat.st_uid, original_stat.st_gid)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise ClerkConfigError(f"atomic write failed for {path}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


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
        description="Write production Clerk env vars for app.altcontext.com. Dry-run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="write destination files (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without writing (default)")
    parser.add_argument("--check", action="store_true", help="GET the derived JWKS URL with a bounded timeout")
    parser.add_argument("--backend-env", type=Path, help="backend env file (production: /opt/acx-backend/prod/.env)")
    parser.add_argument(
        "--frontend-env",
        type=Path,
        help="explicit frontend env artifact for a later Vite build (no deployed app-portal in this tree)",
    )
    parser.add_argument("--publishable-key-file", type=Path, help="0600 file containing pk_live_... (not argv)")
    parser.add_argument("--secret-key-file", type=Path, help="owner-only file containing optional sk_live_...")
    parser.add_argument("--audience", help="required aud claim the Clerk session token template must set")
    parser.add_argument(
        "--authorized-parties",
        action="append",
        dest="authorized_parties",
        help=f"exact azp origin (default {DEFAULT_AUTHORIZED_PARTY}); repeatable",
    )
    return parser


def resolve_secrets(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str],
    stdin: TextIO,
    prompt: bool,
) -> tuple[str, str | None]:
    publishable = _optional_env(environ, PUBLISHABLE_ENV)
    if args.publishable_key_file is not None:
        publishable = load_protected_value(args.publishable_key_file, kind="publishable key", require_owner_only=False)
    if not publishable and prompt and stdin.isatty():
        publishable = input("Clerk publishable key (pk_live_...): ")
    if not publishable:
        raise ClerkConfigError(
            f"publishable key required via {PUBLISHABLE_ENV}, --publishable-key-file, or an interactive prompt"
        )
    secret = _optional_env(environ, SECRET_ENV)
    if args.secret_key_file is not None:
        secret = load_protected_value(args.secret_key_file, kind="secret key", require_owner_only=True)
    return publishable, secret


def print_plan(
    config: DerivedClerkConfig, *, stdout: TextIO, apply: bool, backend: Path | None, frontend: Path | None
) -> None:
    mode = "apply" if apply else "dry-run"
    stdout.write(f"mode={mode}\n")
    stdout.write(f"frontend_api_host={config.frontend_api_host}\n")
    stdout.write(f"ACX_CLERK_ISSUER={config.issuer}\n")
    stdout.write(f"ACX_CLERK_JWKS_URL={config.jwks_url}\n")
    stdout.write(f"ACX_CLERK_AUDIENCE={config.audience}\n")
    stdout.write(f"ACX_CLERK_AUTHORIZED_PARTIES={','.join(config.authorized_parties)}\n")
    stdout.write(f"VITE_CLERK_PUBLISHABLE_KEY={redact(config.publishable_key)}\n")
    stdout.write(f"VITE_CLERK_FAPI={config.issuer}\n")
    if config.secret_key is not None:
        stdout.write(
            f"CLERK_SECRET_KEY={redact(config.secret_key)} (backend only; JWT verification does not require it)\n"
        )
    else:
        stdout.write("CLERK_SECRET_KEY=<omitted> (JWT verification does not require the Clerk secret)\n")
    if backend is not None:
        stdout.write(f"backend_env={backend}\n")
    if frontend is not None:
        stdout.write(f"frontend_env={frontend}\n")
        stdout.write("frontend_note=no committed app-portal; bake VITE_* at a later frontend build\n")


def plan_env_files(
    config: DerivedClerkConfig, *, backend: Path | None, frontend: Path | None
) -> list[tuple[Path, str]]:
    planned: list[tuple[Path, str]] = []
    if backend is not None:
        _assert_safe_destination(backend)
        existing = _read_existing_env(backend)
        planned.append((backend, merge_env_updates(existing, config.backend_updates())))
    if frontend is not None:
        _assert_safe_destination(frontend)
        existing = _read_existing_env(frontend)
        merged = merge_env_updates(existing, config.frontend_updates())
        reject_frontend_secret_boundary(existing, merged)
        planned.append((frontend, merged))
    return planned


def apply_files(config: DerivedClerkConfig, *, backend: Path | None, frontend: Path | None) -> None:
    planned = plan_env_files(config, backend=backend, frontend=frontend)
    _commit_env_files(planned)


def execute(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    jwks_get: Callable[[str], dict[str, object]] | None = None,
    prompt: bool | None = None,
) -> int:
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        if args.apply and args.dry_run:
            raise ClerkConfigError("use either --apply or --dry-run, not both")
        if args.audience is None:
            raise ClerkConfigError("audience is required (session token template must set aud)")
        if args.backend_env is None and args.frontend_env is None and not args.check:
            raise ClerkConfigError("provide --backend-env and/or --frontend-env (or --check)")
        parties = args.authorized_parties or [DEFAULT_AUTHORIZED_PARTY]
        publishable, secret = resolve_secrets(
            args,
            environ=environ,
            stdin=stdin,
            prompt=sys.stdin.isatty() if prompt is None else prompt,
        )
        config = derived_config(
            publishable_key=publishable,
            audience=args.audience,
            authorized_parties=parties,
            secret_key=secret,
        )
        if args.backend_env is not None or args.frontend_env is not None:
            plan_env_files(config, backend=args.backend_env, frontend=args.frontend_env)
        if args.check:
            getter = fetch_jwks if jwks_get is None else jwks_get
            getter(config.jwks_url)
            stdout.write(f"jwks_check=ok url={config.jwks_url}\n")
        print_plan(
            config,
            stdout=stdout,
            apply=bool(args.apply),
            backend=args.backend_env,
            frontend=args.frontend_env,
        )
        if args.apply:
            if args.backend_env is None and args.frontend_env is None:
                raise ClerkConfigError("--apply requires --backend-env and/or --frontend-env")
            apply_files(config, backend=args.backend_env, frontend=args.frontend_env)
            stdout.write("wrote=ok\n")
        return 0
    except ClerkConfigError as exc:
        stderr.write(f"error: {exc}\n")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return execute(args)


def _optional_env(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _single_line_secret(raw: str, *, name: str) -> str:
    if any(ch in raw for ch in "\0"):
        raise ClerkConfigError(f"{name} contains a NUL")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ClerkConfigError(f"{name} must be a single line")
    value = lines[0]
    if any(ch in value for ch in " \t"):
        raise ClerkConfigError(f"{name} must not contain whitespace")
    return value


def _reject_unsafe_env_value(key: str, value: str) -> None:
    if any(ch in key for ch in "\n\r\0="):
        raise ClerkConfigError("env key contains an illegal character")
    if any(ch in value for ch in "\n\r\0"):
        raise ClerkConfigError(f"refusing newline injection in {key}")


def _format_env_value(value: str) -> str:
    _reject_unsafe_env_value("value", value)
    if re.fullmatch(r"[A-Za-z0-9_.:/=+-]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _unquote_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _ordered_keys(updates: Mapping[str, str]) -> list[str]:
    order = list(BACKEND_MANAGED_KEYS) + [SECRET_BACKEND_KEY] + list(FRONTEND_MANAGED_KEYS)
    known = [key for key in order if key in updates]
    extra = sorted(key for key in updates if key not in known)
    return known + extra


def _assert_safe_file(path: Path, *, must_exist: bool, require_owner_only: bool) -> None:
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        if must_exist:
            raise ClerkConfigError(f"missing file: {path}") from exc
        return
    if stat.S_ISLNK(st.st_mode):
        raise ClerkConfigError(f"refusing symlink: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise ClerkConfigError(f"refusing non-regular file: {path}")
    if require_owner_only and st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ClerkConfigError(f"refusing group/world-accessible secret file: {path}")


def _assert_safe_destination(path: Path) -> None:
    if path.is_symlink():
        raise ClerkConfigError(f"refusing symlink destination: {path}")
    try:
        st = path.lstat()
    except FileNotFoundError:
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            raise ClerkConfigError(f"destination directory does not exist: {parent}") from None
        return
    if stat.S_ISLNK(st.st_mode):
        raise ClerkConfigError(f"refusing symlink destination: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise ClerkConfigError(f"refusing non-regular destination: {path}")


def _read_existing_env(path: Path) -> str:
    if not path.exists():
        return ""
    _assert_safe_destination(path)
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClerkConfigError(f"cannot read {path}") from exc


def _commit_env_files(planned: Sequence[tuple[Path, str]]) -> None:
    snapshots: list[tuple[Path, str | None]] = []
    try:
        for path, content in planned:
            snapshots.append((path, _read_existing_env(path) if path.exists() else None))
            # A write can fail after replacement, so recover every attempted destination.
            atomic_write_text(path, content)
    except BaseException as exc:
        rollback_error = _rollback_env_files(snapshots)
        if rollback_error is not None:
            raise ClerkConfigError(
                "partial Clerk env apply; rollback failed and recovery cannot be guaranteed"
            ) from exc
        if isinstance(exc, ClerkConfigError):
            raise
        if not isinstance(exc, Exception):
            raise
        raise ClerkConfigError("atomic write failed during Clerk env apply") from exc


def _rollback_env_files(snapshots: Sequence[tuple[Path, str | None]]) -> BaseException | None:
    last_error: BaseException | None = None
    for path, original in reversed(list(snapshots)):
        try:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_text(path, original)
        except (OSError, ClerkConfigError) as exc:
            last_error = exc
    return last_error


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
