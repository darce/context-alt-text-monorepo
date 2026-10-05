from __future__ import annotations

import json
from pathlib import Path

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
