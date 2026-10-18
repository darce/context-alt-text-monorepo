from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from conftest import load_module


CLI_PATH = Path(__file__).resolve().parents[1] / "render_env.py"


def _targets(*, remote_paths: dict[str, str] | None = None) -> str:
    lines = [
        "version = 1",
        "",
        "[targets.t]",
        'audience = "backend"',
        'envs = ["dev"]',
        'path = "runtime.env"',
    ]
    if remote_paths is not None:
        entries = ", ".join(f"{json.dumps(env)} = {json.dumps(path)}" for env, path in remote_paths.items())
        lines.append(f"remote_paths = {{ {entries} }}")
    lines.append('sections = ["Database"]')
    return "\n".join(lines)


def _host_secret(name: str = "PGPASSWORD") -> str:
    return "\n".join(
        (
            "[[var]]",
            f"name = {json.dumps(name)}",
            'class = "secret"',
            'targets = ["t"]',
            'section = "Database"',
            'example = "example-password"',
            'secret = { dev = "host:" }',
        )
    )


def _manifest(write_manifest, remote_paths: dict[str, str] | None = None):
    return write_manifest(
        _targets(remote_paths=remote_paths),
        **{"10-host-secret": "version = 1\n\n" + _host_secret()},
    )


def test_host_secret_requires_remote_path(write_manifest):
    manifest = load_module("manifest")
    root = _manifest(write_manifest)

    with pytest.raises(manifest.ManifestError) as exc_info:
        manifest.load_manifest(root)

    assert "PGPASSWORD" in str(exc_info.value)
    assert "remote path" in str(exc_info.value)


def test_required_host_secret_without_host_lines_fails_cli(write_manifest, tmp_path: Path):
    remote_paths = {"dev": "/opt/acx-backend/dev/runtime.env"}
    root = _manifest(write_manifest, remote_paths=remote_paths)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "render",
            "--target",
            "t",
            "--env",
            "dev",
            "--root",
            str(root),
            "--repo-root",
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "PGPASSWORD" in result.stderr
    assert not (repo_root / "runtime.env").exists()


def _materialize_case(write_manifest, tmp_path: Path):
    into = "/opt/acx-backend/dev/runtime.env"
    root = _manifest(write_manifest, remote_paths={"dev": into})
    fs_root = tmp_path / "fs"
    runtime_path = fs_root / into.lstrip("/")
    runtime_path.parent.mkdir(parents=True)
    render = load_module("render_env")
    runtime_path.write_text(
        f"{render.HEADER_LINE}\n# materialized target=t env=dev digest=test\n# == Database ==\n",
        encoding="utf-8",
    )
    runtime_path.chmod(0o600)
    return root, fs_root, into, runtime_path


def test_materialize_check_reports_required_host_secret_as_missing(write_manifest, tmp_path: Path):
    materialize = load_module("materialize")
    root, fs_root, into, _ = _materialize_case(write_manifest, tmp_path)
    out = StringIO()
    err = StringIO()

    result = materialize.run(
        root,
        env="dev",
        target="t",
        into=into,
        check=True,
        fs_root=fs_root,
        backup_root=tmp_path / "backups",
        out=out,
        err=err,
    )

    assert result == 1
    assert out.getvalue().splitlines() == ["missing\tPGPASSWORD"]
    assert err.getvalue() == ""


def test_materialize_apply_refuses_missing_required_host_secret(write_manifest, tmp_path: Path):
    materialize = load_module("materialize")
    root, fs_root, into, runtime_path = _materialize_case(write_manifest, tmp_path)
    original = runtime_path.read_bytes()
    out = StringIO()
    err = StringIO()

    result = materialize.run(
        root,
        env="dev",
        target="t",
        into=into,
        fs_root=fs_root,
        backup_root=tmp_path / "backups",
        out=out,
        err=err,
    )

    assert result != 0
    assert "PGPASSWORD" in err.getvalue()
    assert runtime_path.read_bytes() == original
