from __future__ import annotations

import os
from pathlib import Path
import shutil
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
remote_command="${@: -1}"
if [[ ${SHIM_EXEC_REMOTE:-0} == 1 ]]; then
    PATH="$SHIM_REMOTE_PATH:$PATH" bash -c "$remote_command"
    exit $?
fi
if [[ ${SHIM_READ_STDIN:-1} == 1 ]]; then
    cat > "$SHIM_STDIN"
fi
if [[ ${SHIM_MARKER_MODE:-valid} != missing && ${SHIM_RC:-0} != 255 &&
      $remote_command =~ __MATERIALIZE_REMOTE_STAGE_([[:xdigit:]]+)__ ]]; then
    marker_nonce=${BASH_REMATCH[1]}
    marker_stage=${SHIM_STAGE:-materialize}
    if [[ ${SHIM_MARKER_MODE:-valid} == malformed ]]; then
        printf '__MATERIALIZE_REMOTE_STAGE_%s__:invalid:%s\\n' "$marker_nonce" "${SHIM_RC:-0}" >&2
    elif [[ ${SHIM_MARKER_MODE:-valid} == stdout ]]; then
        printf '__MATERIALIZE_REMOTE_STAGE_%s__:%s:%s\\n' \\
            "$marker_nonce" "$marker_stage" "${SHIM_RC:-0}"
    else
        printf '__MATERIALIZE_REMOTE_STAGE_%s__:%s:%s\\n' \\
            "$marker_nonce" "$marker_stage" "${SHIM_RC:-0}" >&2
    fi
fi
exit "${SHIM_RC:-0}"
''')
    (bindir / "ssh").chmod(0o755)

    env = os.environ.copy()
    for key in (
        "OCI_USER",
        "OCI_HOST",
        "SHIM_RC",
        "SHIM_MARKER_MODE",
        "SHIM_STAGE",
        "SHIM_EXEC_REMOTE",
        "SHIM_REMOTE_PATH",
        "SHIM_REMOTE_TMP",
        "SHIM_MKTEMP_RC",
        "SHIM_TAR_RC",
        "SHIM_TAR_FAKE_RENDER",
        "SHIM_SUDO_RC",
        "SHIM_SUDO_LAUNCH",
        "SHIM_MATERIALIZE_RC",
        "SHIM_MATERIALIZE_STDOUT",
        "REAL_TAR",
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


def execute_constructed_remote(remote, tmp_path, *, fake_python=True):
    remote_bin = tmp_path / "remote-bin"
    remote_bin.mkdir()
    (remote_bin / "mktemp").write_text('''#!/bin/bash
if [[ ${SHIM_MKTEMP_RC:-0} != 0 ]]; then
    exit "$SHIM_MKTEMP_RC"
fi
mkdir -p "$SHIM_REMOTE_TMP"
printf '%s\\n' "$SHIM_REMOTE_TMP"
''')
    (remote_bin / "tar").write_text('''#!/bin/bash
if [[ ${SHIM_TAR_FAKE_RENDER:-0} == 1 ]]; then
    destination="${@: -1}"
    cat > /dev/null
    mkdir -p "$destination/scripts/env"
    cat > "$destination/scripts/env/render_env.py" <<'PY'
import os
import sys

if os.environ.get("SHIM_MATERIALIZE_STDOUT") == "1":
    print("materialized stdout")
sys.exit(int(os.environ.get("SHIM_MATERIALIZE_RC", "0")))
PY
    exit 0
fi
if [[ ${SHIM_TAR_RC:-0} != 0 ]]; then
    cat > /dev/null
    exit "$SHIM_TAR_RC"
fi
exec "$REAL_TAR" "$@"
''')
    (remote_bin / "sudo").write_text('''#!/bin/bash
if [[ ${SHIM_SUDO_LAUNCH:-0} == 1 ]]; then
    exec "$@"
fi
exit "${SHIM_SUDO_RC:-1}"
''')
    if fake_python:
        python_script = '''#!/bin/bash
if [[ $1 == -B && $2 == -c ]]; then
    : > "$4"
fi
if [[ ${SHIM_MATERIALIZE_STDOUT:-0} == 1 ]]; then
    printf 'materialized stdout\\n'
fi
exit "${SHIM_MATERIALIZE_RC:-0}"
'''
    else:
        python_script = '''#!/bin/bash
exec "$REAL_PYTHON" "$@"
'''
    (remote_bin / "python3").write_text(python_script)
    for executable in remote_bin.iterdir():
        executable.chmod(0o755)
    remote.update(
        SHIM_EXEC_REMOTE="1",
        SHIM_REMOTE_PATH=str(remote_bin),
        SHIM_REMOTE_TMP=str(tmp_path / "remote-tmp"),
        REAL_TAR=shutil.which("tar"),
    )


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


def test_apply_exit_one_is_remote_materialize_failure_not_drift(remote):
    remote["SHIM_RC"] = "1"

    result = subprocess.run(
        ["bash", str(WRAPPER), "dev", "t", "--apply"],
        env=remote,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert "drift found" not in result.stderr
    assert "remote materialize exited with status 1" in result.stderr


@pytest.mark.parametrize("marker_mode", ["missing", "malformed", "stdout"])
def test_unconfirmed_stage_marker_never_labels_exit_one_as_drift(remote, marker_mode):
    remote.update(SHIM_RC="1", SHIM_MARKER_MODE=marker_mode)

    result = run(remote)

    assert result.returncode == 1
    assert "drift found" not in result.stderr
    assert "stage marker missing or invalid" in result.stderr
    if marker_mode == "stdout":
        assert "__MATERIALIZE_REMOTE_STAGE_" in result.stdout


@pytest.mark.parametrize(
    "bootstrap,code",
    [(stage, code) for stage in ("mktemp", "tar", "sudo") for code in (1, 2, 4, 75)],
)
def test_constructed_remote_command_reports_bootstrap_failures(remote, tmp_path, bootstrap, code):
    execute_constructed_remote(remote, tmp_path)
    remote.update({f"SHIM_{bootstrap.upper()}_RC": str(code)})

    result = run(remote)

    assert result.returncode == code
    assert f"remote bootstrap failed with status {code}" in result.stderr
    assert "drift found" not in result.stderr
    assert "required host secret is missing" not in result.stderr
    assert "remote materialize refused" not in result.stderr


@pytest.mark.parametrize(
    "args,code,meaning",
    [
        ([], 1, "drift found (remote check exit 1)"),
        (["--apply"], 1, "remote materialize exited with status 1"),
        ([], 2, "remote materialize refused with status 2"),
        ([], 4, "required host secret is missing (remote materialize exit 4)"),
        ([], 75, "remote materialize lock or lease busy (exit 75)"),
    ],
)
def test_constructed_remote_command_reports_confirmed_materialize_status(
    remote, tmp_path, args, code, meaning
):
    execute_constructed_remote(remote, tmp_path)
    remote.update(SHIM_SUDO_LAUNCH="1", SHIM_MATERIALIZE_RC=str(code))

    result = subprocess.run(
        ["bash", str(WRAPPER), "dev", "t", *args],
        env=remote,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == code
    assert meaning in result.stderr


def test_constructed_remote_command_streams_stdout(remote, tmp_path):
    execute_constructed_remote(remote, tmp_path)
    remote.update(SHIM_SUDO_LAUNCH="1", SHIM_MATERIALIZE_STDOUT="1")

    result = run(remote)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "materialized stdout\n"


def test_constructed_remote_command_runs_python_materializer_wrapper(remote, tmp_path):
    execute_constructed_remote(remote, tmp_path, fake_python=False)
    remote.update(SHIM_SUDO_LAUNCH="1", SHIM_TAR_FAKE_RENDER="1", SHIM_MATERIALIZE_RC="1")

    result = run(remote)

    assert result.returncode == 1
    assert "drift found (remote check exit 1)" in result.stderr
    assert "stage marker missing or invalid" not in result.stderr
