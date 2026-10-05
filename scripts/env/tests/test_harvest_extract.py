from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import load_module


def _var(
    name: str,
    *,
    cls: str = "config",
    source: str = 'values = { prod = "manifest-value" }',
    derive_vault_map: bool = False,
) -> str:
    derive_option = "derive_vault_map = true\n" if derive_vault_map else ""
    return f'''[[var]]
name = "{name}"
class = "{cls}"
targets = ["t"]
section = "Runtime"
example = "safe-example"
{derive_option}{source}
'''


def _root(write_manifest, *variables: str, remote_path: bool = True) -> Path:
    remote = 'remote_paths = { prod = "/opt/acx-backend/prod/.env" }\n' if remote_path else ""
    targets = f'''version = 1

[targets.t]
audience = "backend"
envs = ["prod"]
{remote}sections = ["Runtime"]
'''
    return write_manifest(targets, **{"10-harvest": "version = 1\n" + "\n".join(variables)})


def _invoke(module, root: Path, fs_root: Path) -> int:
    return module.main([
        "--root", str(root), "--target", "t", "--env", "prod", "--fs-root", str(fs_root),
    ])


def test_extracts_safe_values_and_withholds_secret_material(write_manifest, tmp_path: Path, capsys):
    module = load_module("harvest_extract")
    root = _root(
        write_manifest,
        _var("LOG_LEVEL"),
        _var("DB_PASSWORD", cls="secret", source='secret = { prod = "host:" }'),
        _var("PUBLIC_NOTICE", cls="public"),
        _var("PUBLIC_ASSET"),
        _var("SERVICE_DSN"),
        _var("PLACEHOLDER"),
        _var("DERIVED_CONFIG", source='derive = "${LOG_LEVEL}"'),
        _var("DERIVED_MAP", source="", derive_vault_map=True),
        _var("DUPLICATE"),
        _var("MULTI"),
        _var("MISSING"),
        _var("PUBLISHABLE_KEY"),
        _var("PUBLISHABLE_KEY_PASSWORD"),
    )
    env_path = tmp_path / "opt/acx-backend/prod/.env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "LOG_LEVEL=\"info level\"\n"
        "DB_PASSWORD=fake-secret-value\n"
        "PUBLIC_NOTICE=public-value\n"
        "PUBLIC_ASSET=sk_live_fake-value\n"
        "SERVICE_DSN=postgres://u:pw@h/db\n"
        "PLACEHOLDER=${OTHER}\n"
        "DERIVED_CONFIG=derived-source-value\n"
        "DERIVED_MAP=derived-map-value\n"
        "DUPLICATE=one\nDUPLICATE=two\n"
        "MULTI=one two\n"
        "PUBLISHABLE_KEY=pk_example\n"
        "PUBLISHABLE_KEY_PASSWORD=safe-name-sensitive\n"
        "EXTRA=unmanaged-value\n",
        encoding="utf-8",
    )

    assert _invoke(module, root, tmp_path) == 0

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == ""
    assert result == {
        "version": 1,
        "target": "t",
        "env": "prod",
        "values": {
            "LOG_LEVEL": "info level",
            "PLACEHOLDER": "${OTHER}",
            "PUBLISHABLE_KEY": "pk_example",
            "PUBLIC_NOTICE": "public-value",
        },
        "withheld": {
            "secret": ["DB_PASSWORD"],
            "derived": ["DERIVED_CONFIG", "DERIVED_MAP"],
            "unmanaged": ["EXTRA"],
            "missing": ["MISSING"],
            "secret_looking": ["PUBLIC_ASSET", "PUBLISHABLE_KEY_PASSWORD", "SERVICE_DSN"],
            "unparsed": ["DUPLICATE", "MULTI"],
        },
    }
    for fake_secret in (
        "fake-secret-value", "sk_live_fake-value", "postgres://u:pw@h/db", "safe-name-sensitive",
        "derived-source-value", "derived-map-value", "unmanaged-value", "one", "two",
    ):
        assert fake_secret not in captured.out + captured.err


def test_missing_remote_path_fails_with_names_only(write_manifest, tmp_path: Path, capsys):
    module = load_module("harvest_extract")
    root = _root(write_manifest, _var("LOG_LEVEL"), remote_path=False)

    assert _invoke(module, root, tmp_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "t" in captured.err and "prod" in captured.err
    assert "manifest-value" not in captured.err


def test_missing_env_file_fails_with_names_only(write_manifest, tmp_path: Path, capsys):
    module = load_module("harvest_extract")
    root = _root(write_manifest, _var("LOG_LEVEL"))

    assert _invoke(module, root, tmp_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "t" in captured.err and "prod" in captured.err
    assert "manifest-value" not in captured.err


@pytest.mark.parametrize("value", [
    "postgresql://db/app?password=pw",
    "https://h/x?token=abc",
    "https://h/x?API-KEY=abc",
    "https://h/x?client_secret=",
    "https://h/x?%70assword=pw",
    "https://h/x#access_token=abc",
])
def test_query_credentials_are_withheld(write_manifest, tmp_path: Path, capsys, value):
    module = load_module("harvest_extract")
    root = _root(write_manifest, _var("SERVICE_DSN"))
    env_path = tmp_path / "opt/acx-backend/prod/.env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(f'SERVICE_DSN="{value}"\n', encoding="utf-8")

    assert _invoke(module, root, tmp_path) == 0

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["values"] == {}
    assert result["withheld"]["secret_looking"] == ["SERVICE_DSN"]
    assert value not in captured.out + captured.err
    assert captured.err == ""


@pytest.mark.parametrize("value", [
    "postgresql://db/app?sslmode=require",
    "https://h/x?key_id=example",
    "password=pw",
])
def test_benign_query_values_are_extracted(write_manifest, value):
    module = load_module("harvest_extract")
    root = _root(write_manifest, _var("SERVICE_DSN"))
    result = module.extract(module.load_manifest(root), "t", "prod", f'SERVICE_DSN="{value}"\n')
    assert result["values"] == {"SERVICE_DSN": value}
    assert result["withheld"]["secret_looking"] == []


@pytest.mark.parametrize("location", ["example", "values", "override"])
def test_public_build_query_credentials_are_rejected(write_manifest, location):
    module = load_module("harvest_extract")
    value = "https://h/x?api_key=abc"
    variable = _var("VITE_SERVICE_URL", cls="public")
    if location == "example":
        variable = variable.replace("safe-example", value)
    elif location == "values":
        variable = variable.replace("manifest-value", value)
    else:
        variable += f'''\n[[override]]
name = "VITE_SERVICE_URL"
target = "t"
example = "{value}"
'''
    root = write_manifest('''version = 1
[targets.t]
audience = "public_build"
envs = ["prod"]
sections = ["Runtime"]
''', **{"10-harvest": "version = 1\n" + variable})

    with pytest.raises(module.ManifestError, match="URL credentials") as exc:
        module.load_manifest(root)
    assert "VITE_SERVICE_URL" in str(exc.value)
    assert value not in str(exc.value)
