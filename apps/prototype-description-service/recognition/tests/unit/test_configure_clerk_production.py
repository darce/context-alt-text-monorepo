"""Unit tests for the read-only Clerk production manifest validator."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import shutil
import subprocess
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

    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        "parsePortalConfig(env);\n",
        encoding="utf-8",
    )
    module.validate_frontend_modules(config, [reachable])


def test_frontend_resolves_static_config_aliases(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const liveKey = "{FAKE_LIVE_KEY}"; const liveFapi = "https://clerk.altcontext.com";\n'
        'const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, '
        'VITE_PORTAL_ENABLED: "true" };\n'
        "parsePortalConfig(env);\n",
        encoding="utf-8",
    )

    module.validate_frontend_modules(config, [reachable])


def test_frontend_resolves_vite_object_alias_property_forwarding(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const ef = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        f'const IT = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        "const a = IT;\n"
        'const diagnostic = "React reported } ] ) in a message";\n'
        "parsePortalConfig({"
        "VITE_CLERK_PUBLISHABLE_KEY: a.VITE_CLERK_PUBLISHABLE_KEY, "
        "VITE_CLERK_FAPI: a.VITE_CLERK_FAPI, "
        "VITE_PORTAL_ENABLED: a.VITE_PORTAL_ENABLED });\n",
        encoding="utf-8",
    )

    module.validate_frontend_modules(config, [reachable])


@pytest.mark.parametrize(
    "mutation",
    [
        'env.VITE_CLERK_FAPI = "https://stale.fake-review.invalid";',
        'delete env.VITE_CLERK_FAPI;',
        'env["VITE_CLERK_FAPI"] = "https://stale.fake-review.invalid";',
        'const alias = env; alias.VITE_CLERK_FAPI = "https://stale.fake-review.invalid";',
        "inspect(env);",
    ],
    ids=["property-write", "delete", "computed-write", "alias-write", "unsupported-escape"],
)
def test_frontend_rejects_config_mutation_or_escape_before_consumption(tmp_path: Path, mutation: str) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        f"{mutation}\nparsePortalConfig(env);\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError):
        module.validate_frontend_modules(config, [reachable])


@pytest.mark.parametrize(
    "member",
    [
        '["VITE_CLERK_FAPI"]: "https://stale.fake-review.invalid"',
        'get VITE_CLERK_FAPI() { return "https://stale.fake-review.invalid"; }',
        '[overrideName]: "https://stale.fake-review.invalid"',
    ],
    ids=["computed-duplicate", "getter-override", "unknown-computed-member"],
)
def test_frontend_rejects_computed_and_accessor_config_members(tmp_path: Path, member: str) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        f'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true", {member} }};\n'
        "parsePortalConfig(env);\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
        module.validate_frontend_modules(config, [reachable])


@pytest.mark.parametrize(
    "mutation",
    [
        'const note = `${env.VITE_CLERK_FAPI = "https://stale.fake-review.invalid"}`;',
        'const alias = env; const note = `${`${alias.VITE_CLERK_FAPI = "https://stale.fake-review.invalid"}`}`;',
    ],
    ids=["template-mutation", "nested-template-alias-mutation"],
)
def test_frontend_rejects_config_mutation_in_template_expressions(tmp_path: Path, mutation: str) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        f"{mutation}\nparsePortalConfig(env);\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
        module.validate_frontend_modules(config, [reachable])


def test_frontend_keeps_template_text_opaque(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        'const note = `text mentioning env.VITE_CLERK_FAPI = "https://stale.fake-review.invalid"`;\n'
        "parsePortalConfig(env);\n",
        encoding="utf-8",
    )

    module.validate_frontend_modules(config, [reachable])


@pytest.mark.parametrize(
    "aliases",
    [
        (
            f'const fapi = "https://clerk.altcontext.com"; '
            f'function build(fapi) {{ parsePortalConfig({{VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
            'VITE_CLERK_FAPI: fapi, VITE_PORTAL_ENABLED: "true"}); } '
            'build("https://stale.fake-review.invalid");'
        ),
        (
            f'const fapi = "https://clerk.altcontext.com"; '
            f'function build() {{ let fapi = "https://stale.fake-review.invalid"; '
            f'parsePortalConfig({{VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
            'VITE_CLERK_FAPI: fapi, VITE_PORTAL_ENABLED: "true"}); } build();'
        ),
        (
            f'const fapi = "https://clerk.altcontext.com"; '
            f'const build = (fapi) => {{ parsePortalConfig({{VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
            'VITE_CLERK_FAPI: fapi, VITE_PORTAL_ENABLED: "true"}); }; '
            'build("https://stale.fake-review.invalid");'
        ),
    ],
    ids=["function-parameter", "let-shadow", "arrow-parameter"],
)
def test_frontend_rejects_static_alias_shadowed_by_nearer_binding(tmp_path: Path, aliases: str) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f"{aliases}\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
        module.validate_frontend_modules(config, [reachable])


@pytest.mark.parametrize(
    "suffix",
    [
        'if (true) /[}]/.test("}");',
        'const unused = typeof /[}]/;',
        'const unused = void /[/]/;',
        'const quotient = 12 / 3;',
    ],
    ids=["control-header-regex", "typeof-regex", "void-regex-class", "division"],
)
def test_frontend_accepts_valid_regex_and_division_syntax(tmp_path: Path, suffix: str) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        f"parsePortalConfig(env);\n{suffix}\n",
        encoding="utf-8",
    )
    node = shutil.which("node")
    if node:
        checked = subprocess.run([node, "--check", str(reachable)], capture_output=True, text=True, check=False)
        assert checked.returncode == 0, checked.stdout + checked.stderr

    module.validate_frontend_modules(config, [reachable])


@pytest.mark.parametrize(
    "aliases",
    [
        (
            f'const liveKey = "{FAKE_LIVE_KEY}" + "-STALE-FAKE"; '
            'const liveFapi = "https://clerk.altcontext.com"; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };'
        ),
        (
            f'const expectedKey = "{FAKE_LIVE_KEY}"; const suffix = "-STALE-FAKE"; '
            "const liveKey = expectedKey + suffix; "
            'const liveFapi = "https://clerk.altcontext.com"; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };'
        ),
        (
            f'const liveKey = "{FAKE_LIVE_KEY}"; '
            'const liveFapi = "https://clerk.altcontext.com" + ".stale"; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };'
        ),
        (
            f'const liveKey = "{FAKE_LIVE_KEY}"; '
            'const expectedFapi = "https://clerk.altcontext.com"; const suffix = ".stale"; '
            "const liveFapi = expectedFapi + suffix; "
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };'
        ),
        (
            f'const expectedConfig = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
            'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" }; '
            f'const otherConfig = {{ ["VITE_CLERK_PUBLISHABLE_KEY"]: "{FAKE_LIVE_KEY}", '
            '["VITE_CLERK_FAPI"]: "https://other.altcontext.com", '
            '["VITE_PORTAL_ENABLED"]: "true" }; '
            "const env = expectedConfig && otherConfig;"
        ),
    ],
    ids=["key-literal-concat", "key-identifier-concat", "fapi-literal-concat", "fapi-identifier-concat", "object-logical-alias"],
)
def test_frontend_rejects_incomplete_static_alias_initializers(tmp_path: Path, aliases: str) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f"{aliases}\nparsePortalConfig(env);\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError):
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


@pytest.mark.parametrize(
    ("fapi_value", "decoy"),
    [
        ("https://other.altcontext.com", 'const note = "https://clerk.altcontext.com";'),
        ("https://other.altcontext.com", "// https://clerk.altcontext.com"),
        ("https://clerk.altcontext.com.evil", ""),
    ],
    ids=["unrelated-literal", "comment", "hostname-prefix"],
)
def test_frontend_requires_matching_fapi_in_the_portal_config_record(
    tmp_path: Path, fapi_value: str, decoy: str
) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        f'VITE_CLERK_FAPI: "{fapi_value}", VITE_PORTAL_ENABLED: "true" }};\n'
        f"{decoy}\nparsePortalConfig(env);\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
        module.validate_frontend_modules(config, [reachable])


def test_frontend_rejects_contradictory_fapi_in_reachable_config_records(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    entry = tmp_path / "entry.js"
    chunk = tmp_path / "chunk.js"
    entry.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n',
        encoding="utf-8",
    )
    chunk.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://other.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        "parsePortalConfig(env);\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
        module.validate_frontend_modules(config, [entry, chunk])


def test_frontend_does_not_accept_an_unconsumed_config_decoy(tmp_path: Path) -> None:
    module = _load_script()
    config = module.load_production_config(_manifest_root(tmp_path))
    reachable = tmp_path / "entry.js"
    reachable.write_text(
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://other.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n'
        "parsePortalConfig(env);\n"
        f'const unused = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" };\n',
        encoding="utf-8",
    )

    with pytest.raises(module.ClerkConfigError, match="VITE_CLERK_FAPI"):
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
