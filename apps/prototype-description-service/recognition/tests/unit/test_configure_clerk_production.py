"""Unit tests for scripts/configure_clerk_production.py."""

from __future__ import annotations

import base64
import importlib.util
import os
import stat
import sys
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _SERVICE_ROOT / "scripts" / "configure_clerk_production.py"
LIVE_HOST = "clerk.altcontext.com"
AUDIENCE = "altcontext-portal"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("configure_clerk_production", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pk_live(host: str = LIVE_HOST) -> str:
    payload = base64.b64encode(f"{host}$".encode("ascii")).decode("ascii").rstrip("=")
    return f"pk_live_{payload}"


def _pk_test(host: str = "example.accounts.dev") -> str:
    payload = base64.b64encode(f"{host}$".encode("ascii")).decode("ascii").rstrip("=")
    return f"pk_test_{payload}"


def _write_key(path: Path, value: str, *, mode: int = 0o600) -> Path:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _run(
    module: ModuleType,
    argv: list[str],
    *,
    environ: dict[str, str] | None = None,
    jwks_get=None,
) -> tuple[int, str, str]:
    parser = module.build_parser()
    args = parser.parse_args(argv)
    stdout = StringIO()
    stderr = StringIO()
    code = module.execute(
        args,
        environ=environ or {},
        stdin=StringIO(),
        stdout=stdout,
        stderr=stderr,
        jwks_get=jwks_get,
        prompt=False,
    )
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def cli() -> ModuleType:
    return _load_script()


def test_rejects_development_publishable_key(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_test())
    backend = tmp_path / "backend.env"
    code, _out, err = _run(
        cli,
        [
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
            "--apply",
        ],
    )
    assert code == 1
    assert "pk_test_" in err
    assert not backend.exists()


def test_rejects_development_secret_key(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    secret_file = _write_key(tmp_path / "sk", "sk_test_not-for-production-use")
    backend = tmp_path / "backend.env"
    code, _out, err = _run(
        cli,
        [
            "--publishable-key-file",
            str(key_file),
            "--secret-key-file",
            str(secret_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
            "--apply",
        ],
    )
    assert code == 1
    assert "sk_test_" in err
    assert not backend.exists()


@pytest.mark.parametrize(
    "host",
    [
        "not a host",
        "clerk.example.com/path",
        "localhost",
        "clean-mayfly.clerk.accounts.dev",
        "clerk.altcontext.com:443",
        "",
    ],
)
def test_rejects_malformed_or_dev_host(cli: ModuleType, host: str) -> None:
    if host == "":
        payload = base64.b64encode(b"$").decode("ascii")
        key = f"pk_live_{payload}"
    elif host == "not a host":
        payload = base64.b64encode(b"not a host$").decode("ascii")
        key = f"pk_live_{payload}"
    else:
        key = _pk_live(host)
    with pytest.raises(cli.ClerkConfigError):
        cli.decode_publishable_key(key)


def test_decode_derives_https_issuer_and_jwks(cli: ModuleType) -> None:
    config = cli.derived_config(
        publishable_key=_pk_live(),
        audience=AUDIENCE,
        authorized_parties=["https://app.altcontext.com"],
    )
    assert config.issuer == "https://clerk.altcontext.com"
    assert config.jwks_url == "https://clerk.altcontext.com/.well-known/jwks.json"
    assert config.audience == AUDIENCE
    assert config.authorized_parties == ("https://app.altcontext.com",)
    assert "VITE_CLERK_PUBLISHABLE_KEY" not in config.backend_updates()
    assert "CLERK_SECRET_KEY" not in config.backend_updates()
    assert config.frontend_updates()["VITE_CLERK_FAPI"] == config.issuer


def test_authorized_parties_default_exact_app_origin(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"
    code, out, err = _run(
        cli,
        [
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
        ],
    )
    assert code == 0, err
    assert "ACX_CLERK_AUTHORIZED_PARTIES=https://app.altcontext.com" in out
    assert not backend.exists()


def test_dry_run_does_not_write(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"
    backend.write_text("COMPOSE_PROJECT_NAME=acx-prod\n", encoding="utf-8")
    original = backend.read_bytes()
    code, out, err = _run(
        cli,
        [
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
        ],
    )
    assert code == 0, err
    assert "mode=dry-run" in out
    assert backend.read_bytes() == original


def test_apply_preserves_unrelated_and_omits_browser_secret_from_backend(cli: ModuleType, tmp_path: Path) -> None:
    key = _pk_live()
    key_file = _write_key(tmp_path / "pk", key)
    secret_file = _write_key(tmp_path / "sk", "sk_live_backend-only-secret-value")
    backend = tmp_path / ".env"
    backend.write_text("COMPOSE_PROJECT_NAME=acx-prod\nACX_ENV=prod\n", encoding="utf-8")
    frontend = tmp_path / "app-portal.env"
    code, out, err = _run(
        cli,
        [
            "--apply",
            "--publishable-key-file",
            str(key_file),
            "--secret-key-file",
            str(secret_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
            "--frontend-env",
            str(frontend),
        ],
    )
    assert code == 0, err
    backend_text = backend.read_text(encoding="utf-8")
    frontend_text = frontend.read_text(encoding="utf-8")
    assert "COMPOSE_PROJECT_NAME=acx-prod" in backend_text
    assert "ACX_ENV=prod" in backend_text
    assert "ACX_CLERK_ISSUER=https://clerk.altcontext.com" in backend_text
    assert "ACX_CLERK_JWKS_URL=https://clerk.altcontext.com/.well-known/jwks.json" in backend_text
    assert f"ACX_CLERK_AUDIENCE={AUDIENCE}" in backend_text
    assert "ACX_CLERK_AUTHORIZED_PARTIES=https://app.altcontext.com" in backend_text
    assert "CLERK_SECRET_KEY=sk_live_backend-only-secret-value" in backend_text
    assert "VITE_CLERK_PUBLISHABLE_KEY" not in backend_text
    assert key not in backend_text
    assert f"VITE_CLERK_PUBLISHABLE_KEY={key}" in frontend_text
    assert "VITE_CLERK_FAPI=https://clerk.altcontext.com" in frontend_text
    assert "CLERK_SECRET_KEY" not in frontend_text
    assert "sk_live_backend-only-secret-value" not in frontend_text
    assert stat.S_IMODE(backend.stat().st_mode) == 0o600
    assert stat.S_IMODE(frontend.stat().st_mode) == 0o600
    assert key not in out
    assert "sk_live_backend-only-secret-value" not in out
    assert key not in err
    assert "sk_live_backend-only-secret-value" not in err
    assert "pk_live_<redacted>" in out


def test_does_not_leak_key_from_environment(cli: ModuleType, tmp_path: Path) -> None:
    key = _pk_live()
    backend = tmp_path / ".env"
    code, out, err = _run(
        cli,
        ["--audience", AUDIENCE, "--backend-env", str(backend)],
        environ={"CLERK_PUBLISHABLE_KEY": key},
    )
    assert code == 0, err
    assert key not in out
    assert key not in err


def test_refuses_symlink_destination(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    real = tmp_path / "real.env"
    real.write_text("ACX_ENV=prod\n", encoding="utf-8")
    link = tmp_path / "link.env"
    link.symlink_to(real)
    code, _out, err = _run(
        cli,
        [
            "--apply",
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(link),
        ],
    )
    assert code == 1
    assert "symlink" in err
    assert real.read_text(encoding="utf-8") == "ACX_ENV=prod\n"


def test_rejects_contradictory_duplicate_vars(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"
    backend.write_text("ACX_CLERK_AUDIENCE=one\nACX_CLERK_AUDIENCE=two\n", encoding="utf-8")
    code, _out, err = _run(
        cli,
        [
            "--apply",
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
        ],
    )
    assert code == 1
    assert "contradictory duplicate" in err
    assert backend.read_text(encoding="utf-8") == "ACX_CLERK_AUDIENCE=one\nACX_CLERK_AUDIENCE=two\n"


def test_rejects_newline_injection_in_audience(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"
    code, _out, err = _run(
        cli,
        [
            "--apply",
            "--publishable-key-file",
            str(key_file),
            "--audience",
            "portal\nINJECTED=1",
            "--backend-env",
            str(backend),
        ],
    )
    assert code == 1
    assert "newline" in err or "audience" in err
    assert not backend.exists()


def test_failure_atomicity_leaves_destination_unchanged(
    cli: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"
    original = "COMPOSE_PROJECT_NAME=acx-prod\nKEEP=yes\n"
    backend.write_text(original, encoding="utf-8")
    os.chmod(backend, 0o600)

    def boom(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(cli.os, "replace", boom)
    code, _out, err = _run(
        cli,
        [
            "--apply",
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
        ],
    )
    assert code == 1
    assert "atomic write failed" in err
    assert backend.read_text(encoding="utf-8") == original
    leftovers = list(tmp_path.glob(".env.*.tmp"))
    assert leftovers == []


def test_apply_is_idempotent(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"
    backend.write_text("COMPOSE_PROJECT_NAME=acx-prod\n", encoding="utf-8")
    argv = [
        "--apply",
        "--publishable-key-file",
        str(key_file),
        "--audience",
        AUDIENCE,
        "--backend-env",
        str(backend),
    ]
    first, _, err1 = _run(cli, argv)
    assert first == 0, err1
    once = backend.read_text(encoding="utf-8")
    second, _, err2 = _run(cli, argv)
    assert second == 0, err2
    assert backend.read_text(encoding="utf-8") == once


def test_check_does_not_write_and_fails_closed(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    backend = tmp_path / ".env"

    def fail(_url: str) -> dict[str, object]:
        raise cli.ClerkConfigError("JWKS check failed")

    code, _out, err = _run(
        cli,
        [
            "--check",
            "--apply",
            "--publishable-key-file",
            str(key_file),
            "--audience",
            AUDIENCE,
            "--backend-env",
            str(backend),
        ],
        jwks_get=fail,
    )
    assert code == 1
    assert "JWKS check failed" in err
    assert not backend.exists()


def test_check_success_is_not_fabricated(cli: ModuleType, tmp_path: Path) -> None:
    key_file = _write_key(tmp_path / "pk", _pk_live())
    seen: list[str] = []

    def ok(url: str) -> dict[str, object]:
        seen.append(url)
        return {"keys": [{"kty": "RSA", "kid": "x"}]}

    code, out, err = _run(
        cli,
        ["--check", "--publishable-key-file", str(key_file), "--audience", AUDIENCE],
        jwks_get=ok,
    )
    assert code == 0, err
    assert seen == ["https://clerk.altcontext.com/.well-known/jwks.json"]
    assert "jwks_check=ok" in out
    assert "wrote=" not in out


def test_parser_has_no_secret_value_flags(cli: ModuleType) -> None:
    help_text = cli.build_parser().format_help()
    assert "--publishable-key " not in f" {help_text} "
    assert "--secret-key " not in f" {help_text} "
    assert "--publishable-key-file" in help_text
    assert "--secret-key-file" in help_text
