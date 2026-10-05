from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "scripts/env/materialize_remote.sh"


@pytest.fixture
def remote(tmp_path):
    manifest = tmp_path / "manifest"
    manifest_dir = manifest / "manifest.d"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "targets.toml").write_text('''
        version = 1
        [targets.t]
        audience = "backend"
        envs = ["dev"]
        sections = ["S"]
        remote_paths = {dev = "/opt/acx-backend/dev/.env"}
    ''')
    (manifest_dir / "10-remote.toml").write_text('''
        version = 1
        [[var]]
        name = "LOG_LEVEL"
        class = "config"
        targets = ["t"]
        section = "S"
        example = "info"
        values = {dev = "info"}
    ''')

    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text('''#!/bin/bash
printf '%s\\0' "$@" > "$SHIM_ARGV"
if [[ ${SHIM_READ_STDIN:-1} == 1 ]]; then
    cat > "$SHIM_STDIN"
fi
exit "${SHIM_RC:-0}"
''')
    (bindir / "ssh").chmod(0o755)

    env = os.environ.copy()
    for key in (
        "OCI_USER",
        "OCI_HOST",
        "SHIM_RC",
        "ENV_MATERIALIZE_SSH_CONNECT_TIMEOUT",
        "ENV_MATERIALIZE_SSH_SERVER_ALIVE_INTERVAL",
        "ENV_MATERIALIZE_SSH_SERVER_ALIVE_COUNT_MAX",
        "SHIM_READ_STDIN",
    ):
        env.pop(key, None)
    env.update(
        PATH=f"{bindir}:{REPO / '.venv/bin'}:{env.get('PATH', '')}",
        ENV_MANIFEST_ROOT=str(manifest),
        SHIM_ARGV=str(tmp_path / "argv"),
        SHIM_STDIN=str(tmp_path / "stdin"),
        REAL_PYTHON=sys.executable,
    )
    return env


def run(remote):
    return subprocess.run(
        ["bash", str(WRAPPER), "dev", "t"],
        env=remote,
        capture_output=True,
        text=True,
        timeout=30,
    )


def ssh_args(remote):
    return Path(remote["SHIM_ARGV"]).read_bytes()[:-1].decode().split("\0")


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, {"ConnectTimeout": "15", "ServerAliveInterval": "15", "ServerAliveCountMax": "4"}),
        (
            {
                "ENV_MATERIALIZE_SSH_CONNECT_TIMEOUT": "8",
                "ENV_MATERIALIZE_SSH_SERVER_ALIVE_INTERVAL": "6",
                "ENV_MATERIALIZE_SSH_SERVER_ALIVE_COUNT_MAX": "2",
            },
            {"ConnectTimeout": "8", "ServerAliveInterval": "6", "ServerAliveCountMax": "2"},
        ),
    ],
)
def test_wrapper_bounds_ssh_connection_and_session(remote, overrides, expected):
    remote.update(overrides)

    result = run(remote)

    assert result.returncode == 0, result.stderr
    args = ssh_args(remote)
    assert "-o" in args
    for key, value in expected.items():
        assert f"{key}={value}" in args
    assert "BatchMode=yes" in args


def test_wrapper_reports_tar_producer_failure_after_streaming(remote):
    shim = Path(remote["PATH"].split(":", 1)[0]) / "python3"
    shim.write_text('''#!/bin/bash
if [[ $1 == - && $# == 3 ]]; then
    "$REAL_PYTHON" "$@"
    producer_status=$?
    (( producer_status == 0 )) || exit "$producer_status"
    exit 23
fi
exec "$REAL_PYTHON" "$@"
''')
    shim.chmod(0o755)

    result = run(remote)

    assert Path(remote["SHIM_STDIN"]).stat().st_size > 0
    assert result.returncode == 23
    assert "tar producer failed with status 23" in result.stderr


def test_wrapper_reports_ssh_failure_when_ssh_closes_stdin(remote):
    remote["SHIM_RC"] = "255"
    remote["SHIM_READ_STDIN"] = "0"

    result = run(remote)

    assert result.returncode == 255
    assert "ssh failed with status 255" in result.stderr
    assert "tar producer failed" not in result.stderr


@pytest.mark.parametrize(
    "status,meaning",
    [
        (1, "drift found (remote check exit 1)"),
        (2, "remote materialize refused with status 2"),
        (4, "required host secret is missing (remote materialize exit 4)"),
        (75, "remote materialize lock or lease busy (exit 75)"),
    ],
)
def test_wrapper_reports_remote_materialize_exit_reason(remote, status, meaning):
    remote["SHIM_RC"] = str(status)

    result = run(remote)

    assert result.returncode == status
    assert meaning in result.stderr
    assert "ssh failed" not in result.stderr
