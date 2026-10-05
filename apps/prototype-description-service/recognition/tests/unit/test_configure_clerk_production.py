"""Unit tests for the read-only Clerk production manifest validator."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import shutil
import sys
from io import StringIO
from pathlib import Path
from types import ModuleType

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = SERVICE_ROOT.parents[1]
SCRIPT = SERVICE_ROOT / "scripts" / "configure_clerk_production.py"
CONFIG_ROOT = REPO_ROOT / "config" / "env"
LIVE_HOST = "clerk.altcontext.com"
FAKE_LIVE_KEY = "pk_live_" + base64.b64encode(f"{LIVE_HOST}$".encode("ascii")).decode("ascii").rstrip("=")


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("configure_clerk_production", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest_root(tmp_path: Path, *, key: str = FAKE_LIVE_KEY, fapi: str = "https://clerk.altcontext.com") -> Path:
    root = tmp_path / "config" / "env"
    shutil.copytree(CONFIG_ROOT, root)
    portal = root / "manifest.d" / "60-app-portal.toml"
    text = portal.read_text(encoding="utf-8")
    text = re.sub(
        r'(values = \{ local = "[^"]+")\s*\}',
        rf'\1, prod = "{key}" }}',
        text,
        count=1,
    )
    text = text.replace(
        'values = { local = "https://saved-frog-4170.clerk.accounts.dev", prod = "https://clerk.altcontext.com" }',
        f'values = {{ local = "https://saved-frog-4170.clerk.accounts.dev", prod = "{fapi}" }}',
        1,
    )
    portal.write_text(text, encoding="utf-8")
    return root


def test_decode_publishable_key_requires_live_custom_domain() -> None:
    module = _load_script()

    assert module.decode_publishable_key(FAKE_LIVE_KEY) == LIVE_HOST
    with pytest.raises(module.ClerkConfigError):
        module.decode_publishable_key("pk_test_not-production")
    with pytest.raises(module.ClerkConfigError):
        module.decode_publishable_key("pk_live_not-base64-host")


def test_manifest_values_validate_as_one_production_contract(tmp_path: Path) -> None:
    module = _load_script()

    config = module.load_production_config(_manifest_root(tmp_path))

    assert config.publishable_key == FAKE_LIVE_KEY
    assert config.frontend_api == "https://clerk.altcontext.com"
    assert config.issuer == config.frontend_api
    assert config.jwks_url == "https://clerk.altcontext.com/.well-known/jwks.json"
    assert config.audience == "altcontext-portal"
    assert config.authorized_parties == ("https://app.altcontext.com",)


def test_missing_live_manifest_key_fails_with_variable_name_only(tmp_path: Path) -> None:
    module = _load_script()

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_PUBLISHABLE_KEY") as exc:
        module.load_production_config(CONFIG_ROOT)

    assert FAKE_LIVE_KEY not in str(exc.value)
    assert "pk_test_" not in str(exc.value)


def test_fapi_must_match_the_key_host(tmp_path: Path) -> None:
    module = _load_script()

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
        module.load_production_config(_manifest_root(tmp_path, fapi="https://other.altcontext.com"))


def test_deployment_checks_only_reachable_module_content(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    unreachable_decoy = tmp_path / "unused.js"
    reachable.write_text("import './chunk.js'; const fapi='https://clerk.altcontext.com';", encoding="utf-8")
    unreachable_decoy.write_text(f"const key='{FAKE_LIVE_KEY}';", encoding="utf-8")

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_PUBLISHABLE_KEY"):
        module.validate_frontend_modules(config, [reachable])

    reachable.write_text(f"const key='{FAKE_LIVE_KEY}'; const fapi='https://clerk.altcontext.com';", encoding="utf-8")
    module.validate_frontend_modules(config, [reachable])


def test_reachable_pk_test_key_is_rejected_even_if_live_key_is_also_present(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        f"const configured='{FAKE_LIVE_KEY}'; const fallback='pk_test_fake'; "
        "const fapi='https://clerk.altcontext.com';",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_PUBLISHABLE_KEY"):
        module.validate_frontend_modules(config, [reachable])


def test_cli_has_no_writer_or_secret_input_options() -> None:
    module = _load_script()
    parser = module.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}

    assert "--check" in options
    assert "--verify-assets" in options
    assert "--apply" not in options
    assert "--publishable-key-file" not in options
    assert "--secret-key-file" not in options
    assert "--backend-env" not in options
    assert "--frontend-env" not in options


def test_network_check_is_opt_in_and_uses_validated_jwks_url(tmp_path: Path) -> None:
    module = _load_script()
    root = _manifest_root(tmp_path)
    default_args = module.build_parser().parse_args(["--root", str(root)])
    calls: list[str] = []

    assert module.execute(default_args, stderr=StringIO(), jwks_get=calls.append) == 0
    assert calls == []

    check_args = module.build_parser().parse_args(["--root", str(root), "--check"])
    assert module.execute(check_args, stderr=StringIO(), jwks_get=lambda url: calls.append(url) or {"keys": [{}]}) == 0
    assert calls == ["https://clerk.altcontext.com/.well-known/jwks.json"]


def test_fetch_jwks_bounds_trickling_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script()
    clock = {"now": 10.0}

    class TrickleResponse:
        def __init__(self) -> None:
            self.payload = b'{"keys":[{"kty":"RSA","kid":"x"}]}'
            self.offset = 0

        def read(self, n: int = -1) -> bytes:
            clock["now"] += 0.8
            if self.offset >= len(self.payload):
                return b""
            take = min(4, n, len(self.payload) - self.offset)
            chunk = self.payload[self.offset : self.offset + take]
            self.offset += len(chunk)
            return chunk

        def __enter__(self) -> TrickleResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: TrickleResponse())

    with pytest.raises(module.ClerkConfigError, match="timeout"):
        module.fetch_jwks(
            "https://clerk.altcontext.com/.well-known/jwks.json",
            timeout_s=2.0,
            clock=lambda: clock["now"],
        )


def test_fetch_jwks_accepts_bounded_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script()
    payload = json.dumps({"keys": [{"kty": "RSA", "kid": "fixture"}]}).encode("utf-8")

    class Response:
        def read(self, n: int = -1) -> bytes:
            nonlocal payload
            chunk, payload = payload[:n], payload[n:]
            return chunk

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())

    assert module.fetch_jwks("https://clerk.altcontext.com/.well-known/jwks.json")["keys"]
