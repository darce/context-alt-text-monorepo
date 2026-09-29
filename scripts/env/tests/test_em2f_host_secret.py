from __future__ import annotations

import json
import subprocess
import sys
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
