"""Contract tests for production Clerk manifest validation."""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "apps" / "prototype-description-service" / "scripts" / "configure_clerk_production.py"
CONFIG_ROOT = REPO_ROOT / "config" / "env"
LIVE_HOST = "clerk.altcontext.com"
FAKE_LIVE_KEY = "pk_live_" + base64.b64encode(f"{LIVE_HOST}$".encode("ascii")).decode("ascii").rstrip("=")


def _write_manifest(
    tmp_path: Path,
    *,
    publishable_key: str = FAKE_LIVE_KEY,
    fapi: str = "https://clerk.altcontext.com",
    issuer: str = "https://clerk.altcontext.com",
    jwks_url: str = "https://clerk.altcontext.com/.well-known/jwks.json",
    audience: str = "altcontext-portal",
    authorized_parties: str = "https://app.altcontext.com",
) -> Path:
    root = tmp_path / "config" / "env"
    shutil.copytree(CONFIG_ROOT, root)

    portal = root / "manifest.d" / "60-app-portal.toml"
    portal_text = portal.read_text(encoding="utf-8")
    table_pattern = re.compile(r"(?ms)^\[\[var\]\][ \t]*\n.*?(?=^\[\[var\]\][ \t]*$|\Z)")
    var_tables = list(table_pattern.finditer(portal_text))
    publishable_tables = [
        table
        for table in var_tables
        if re.search(
            r'(?m)^name[ \t]*=[ \t]*"VITE_CLERK_PUBLISHABLE_KEY"[ \t]*$',
            table.group(),
        )
    ]
    assert len(publishable_tables) == 1, "expected exactly one VITE_CLERK_PUBLISHABLE_KEY table"

    publishable_table = publishable_tables[0]
    values_pattern = re.compile(
        r"(?m)^(?P<prefix>[ \t]*values[ \t]*=[ \t]*\{)"
        r"(?P<entries>[^}\n]*)(?P<suffix>\}[ \t]*)$"
    )
    values_lines = list(values_pattern.finditer(publishable_table.group()))
    assert len(values_lines) == 1, "expected exactly one values line in the publishable-key table"

    values_line = values_lines[0]
    entries = values_line.group("entries")
    prod_pattern = re.compile(r'(?P<prefix>\bprod[ \t]*=[ \t]*)"[^"\n]*"')
    prod_values = list(prod_pattern.finditer(entries))
    assert len(prod_values) <= 1, "expected at most one prod value in the publishable-key table"
    if prod_values:
        entries, prod_count = prod_pattern.subn(
            lambda match: f'{match.group("prefix")}"{publishable_key}"', entries, count=1
        )
        assert prod_count == 1, "expected to replace the publishable-key prod value exactly once"
    else:
        separator = ", " if entries.strip() else ""
        entries = f'{entries.rstrip()}{separator}prod = "{publishable_key}"'

    updated_values_line = values_line.group("prefix") + entries + values_line.group("suffix")
    updated_table, values_count = values_pattern.subn(
        lambda _: updated_values_line, publishable_table.group(), count=1
    )
    assert values_count == 1, "expected to update the publishable-key values line exactly once"
    portal_text = (
        portal_text[: publishable_table.start()]
        + updated_table
        + portal_text[publishable_table.end() :]
    )
    portal_text = portal_text.replace(
        'values = { local = "https://saved-frog-4170.clerk.accounts.dev", prod = "https://clerk.altcontext.com" }',
        f'values = {{ local = "https://saved-frog-4170.clerk.accounts.dev", prod = "{fapi}" }}',
        1,
    )
    portal.write_text(portal_text, encoding="utf-8")

    backend = root / "manifest.d" / "30-portal-backend.toml"
    backend_text = backend.read_text(encoding="utf-8")
    replacements = {
        'values = { local = "https://saved-frog-4170.clerk.accounts.dev", prod = "https://clerk.altcontext.com" }':
            f'values = {{ local = "https://saved-frog-4170.clerk.accounts.dev", prod = "{issuer}" }}',
        'values = { local = "https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json", prod = "https://clerk.altcontext.com/.well-known/jwks.json" }':
            f'values = {{ local = "https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json", prod = "{jwks_url}" }}',
        'values = { local = "altcontext-portal", prod = "altcontext-portal" }':
            f'values = {{ local = "altcontext-portal", prod = "{audience}" }}',
        'values = { local = "http://localhost:5173", prod = "https://app.altcontext.com" }':
            f'values = {{ local = "http://localhost:5173", prod = "{authorized_parties}" }}',
    }
    for old, new in replacements.items():
        backend_text = backend_text.replace(old, new, 1)
    backend.write_text(backend_text, encoding="utf-8")
    return root


def _run_cli(
    root: Path, *args: str, input_data: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        input=input_data,
        text=True,
        capture_output=True,
        check=False,
    )


def _config_module(aliases: str) -> str:
    return (
        "function parsePortalConfig(env) { return {"
        "publishableKey: env.VITE_CLERK_PUBLISHABLE_KEY, "
        "fapiOrigin: env.VITE_CLERK_FAPI }; }\n"
        f"{aliases}\nparsePortalConfig(env);\n"
    )


def test_cli_validates_manifest_without_printing_values_or_writing_files(tmp_path: Path) -> None:
    root = _write_manifest(tmp_path)

    result = _run_cli(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("aliases", "expected_name"),
    [
        (
            f'const liveKey = "{FAKE_LIVE_KEY}" + "-STALE-FAKE"; '
            'const liveFapi = "https://clerk.altcontext.com"; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };',
            "VITE_CLERK_PUBLISHABLE_KEY",
        ),
        (
            f'const expectedKey = "{FAKE_LIVE_KEY}"; const suffix = "-STALE-FAKE"; '
            "const liveKey = expectedKey + suffix; "
            'const liveFapi = "https://clerk.altcontext.com"; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };',
            "VITE_CLERK_PUBLISHABLE_KEY",
        ),
        (
            f'const liveKey = "{FAKE_LIVE_KEY}"; '
            'const liveFapi = "https://clerk.altcontext.com" + ".stale"; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };',
            "VITE_CLERK_FAPI",
        ),
        (
            f'const liveKey = "{FAKE_LIVE_KEY}"; '
            'const expectedFapi = "https://clerk.altcontext.com"; const suffix = ".stale"; '
            "const liveFapi = expectedFapi + suffix; "
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };',
            "VITE_CLERK_FAPI",
        ),
        (
            f'const expectedConfig = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
            'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" }; '
            f'const otherConfig = {{ ["VITE_CLERK_PUBLISHABLE_KEY"]: "{FAKE_LIVE_KEY}", '
            '["VITE_CLERK_FAPI"]: "https://other.altcontext.com", '
            '["VITE_PORTAL_ENABLED"]: "true" }; '
            "const env = expectedConfig && otherConfig;",
            "VITE_CLERK_FAPI",
        ),
    ],
    ids=["key-literal-concat", "key-identifier-concat", "fapi-literal-concat", "fapi-identifier-concat", "object-logical-alias"],
)
def test_cli_rejects_asset_alias_prefix_expressions(
    tmp_path: Path, aliases: str, expected_name: str
) -> None:
    root = _write_manifest(tmp_path)
    asset = tmp_path / "entry.js"
    asset.write_text(_config_module(aliases), encoding="utf-8")

    result = _run_cli(root, "--verify-assets", input_data=f"{asset}\n")

    assert result.returncode != 0
    assert expected_name in result.stderr
    assert FAKE_LIVE_KEY not in result.stdout + result.stderr


def test_cli_accepts_complete_static_asset_aliases(tmp_path: Path) -> None:
    root = _write_manifest(tmp_path)
    asset = tmp_path / "entry.js"
    asset.write_text(
        _config_module(
            f'const expectedKey = "{FAKE_LIVE_KEY}"; const liveKey = expectedKey; '
            'const expectedFapi = "https://clerk.altcontext.com"; const liveFapi = expectedFapi; '
            "const env = { VITE_CLERK_PUBLISHABLE_KEY: liveKey, VITE_CLERK_FAPI: liveFapi, "
            'VITE_PORTAL_ENABLED: "true" };'
        ),
        encoding="utf-8",
    )

    result = _run_cli(root, "--verify-assets", input_data=f"{asset}\n")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize(
    "aliases",
    [
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true", '
        '["VITE_CLERK_FAPI"]: "https://stale.fake-review.invalid" };',
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true", '
        'get VITE_CLERK_FAPI() { return "https://stale.fake-review.invalid"; } };',
        f'const env = {{ VITE_CLERK_PUBLISHABLE_KEY: "{FAKE_LIVE_KEY}", '
        'VITE_CLERK_FAPI: "https://clerk.altcontext.com", VITE_PORTAL_ENABLED: "true" }; '
        'const note = `${env.VITE_CLERK_FAPI = "https://stale.fake-review.invalid"}`;',
    ],
    ids=["computed-fapi-override", "getter-fapi-override", "template-fapi-mutation"],
)
def test_cli_rejects_dynamic_portal_config_overrides(tmp_path: Path, aliases: str) -> None:
    root = _write_manifest(tmp_path)
    asset = tmp_path / "entry.js"
    asset.write_text(_config_module(aliases), encoding="utf-8")

    result = _run_cli(root, "--verify-assets", input_data=f"{asset}\n")

    assert result.returncode != 0
    assert "VITE_CLERK_FAPI" in result.stderr
    assert FAKE_LIVE_KEY not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("field", "value", "expected_name"),
    [
        ("publishable_key", "pk_test_not-production", "VITE_CLERK_PUBLISHABLE_KEY"),
        ("publishable_key", "not-a-clerk-key", "VITE_CLERK_PUBLISHABLE_KEY"),
        ("fapi", "https://other.altcontext.com", "VITE_CLERK_FAPI"),
        ("issuer", "https://other.altcontext.com", "ACX_CLERK_ISSUER"),
        ("jwks_url", "https://other.altcontext.com/keys", "ACX_CLERK_JWKS_URL"),
        ("audience", "", "ACX_CLERK_AUDIENCE"),
        ("authorized_parties", "https://elsewhere.altcontext.com", "ACX_CLERK_AUTHORIZED_PARTIES"),
    ],
)
def test_cli_fails_closed_with_names_only_for_invalid_production_values(
    tmp_path: Path, field: str, value: str, expected_name: str
) -> None:
    root = _write_manifest(tmp_path, **{field: value})

    result = _run_cli(root)

    assert result.returncode != 0
    assert expected_name in result.stderr
    assert FAKE_LIVE_KEY not in result.stdout + result.stderr
    assert "other.altcontext.com" not in result.stdout + result.stderr


def test_cli_rejects_writer_and_secret_input_options(tmp_path: Path) -> None:
    root = _write_manifest(tmp_path)

    result = _run_cli(root, "--apply", "--secret-key-file", "/tmp/unused")

    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr
