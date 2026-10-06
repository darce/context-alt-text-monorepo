from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tarfile

import pytest


REPO = Path(__file__).resolve().parents[3]
WRAPPER = REPO / "scripts/env/materialize_remote.sh"
SECRET = "s3cr3t-value"
LITERAL = "remote-literal-config-value"


@pytest.fixture
def remote(tmp_path, write_manifest):
    root = write_manifest('''
        version = 1
        [targets.t]
        audience = "backend"
        envs = ["dev", "prod"]
        sections = ["S"]
        remote_paths = {dev = "/opt/acx-backend/dev/.env", prod = "/opt/acx-backend/prod/.env"}
    ''', **{"10-remote": f'''
        version = 1
        [[var]]
        name = "LOG_LEVEL"
        class = "config"
        targets = ["t"]
        section = "S"
        example = "info"
        values = {{dev = "{LITERAL}", prod = "{LITERAL}"}}
        [[var]]
        name = "PGPASSWORD"
        class = "secret"
        targets = ["t"]
        section = "S"
        example = "password"
        secret = {{dev = "host:", prod = "host:"}}
    '''})
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "ssh"
    shim.write_text('''#!/bin/bash
printf 'call\\n' >> "$SHIM_CALLS"
printf '%s\\0' "$@" > "$SHIM_ARGV"
cat > "$SHIM_STDIN"
exit "${SHIM_RC:-0}"
''')
    shim.chmod(0o755)
    env = os.environ.copy()
    for key in ("OCI_USER", "OCI_HOST", "SHIM_RC", "ENV", "TARGET", "APPLY",
                "ADOPT", "CONFIRM", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"):
        env.pop(key, None)
    env.pop("ENV_MATERIALIZE_OCI_BIN", None)
    env.update(PATH=f"{bindir}:{REPO / '.venv/bin'}:{env.get('PATH', '')}",
               ENV_MANIFEST_ROOT=str(root), PGPASSWORD=SECRET,
               SHIM_ARGV=str(tmp_path / "argv"),
               SHIM_STDIN=str(tmp_path / "stdin"),
               SHIM_CALLS=str(tmp_path / "calls"))
    return env


def run(remote, *args, make=False):
    command = (["make", "-s", "-C", str(REPO), "env-materialize"] if make
               else ["bash", str(WRAPPER)])
    result = subprocess.run(command + list(args), env=remote, capture_output=True,
                            text=True, timeout=30)
    assert SECRET not in result.stdout
    assert SECRET not in result.stderr
    return result


def ssh_args(remote):
    path = Path(remote["SHIM_ARGV"])
    assert path.exists(), "wrapper must invoke ssh"
    data = path.read_bytes()
    assert SECRET.encode() not in data
    assert LITERAL.encode() not in data
    assert Path(remote["SHIM_CALLS"]).read_text() == "call\n"
    assert data.endswith(b"\0")
    return data[:-1].decode().split("\0")


def no_ssh(remote):
    assert not Path(remote["SHIM_CALLS"]).exists()
    assert not Path(remote["SHIM_ARGV"]).exists()
    assert not Path(remote["SHIM_STDIN"]).exists()


@pytest.mark.parametrize("flags,check,adopt", [
    ([], True, False), (["--check"], True, False),
    (["--apply"], False, False), (["--apply", "--adopt"], False, True),
])
def test_wrapper_forwards_materialize_mode(remote, flags, check, adopt):
    result = run(remote, "dev", "t", *flags)
    assert result.returncode == 0, result.stderr
    command = ssh_args(remote)[-1]
    assert ("--check" in command) == check
    assert ("--adopt" in command) == adopt


@pytest.mark.parametrize("overrides,destination", [
    ({}, "ubuntu@acx-backend.tail1a44b8.ts.net"),
    ({"OCI_USER": "tester", "OCI_HOST": "fixture.invalid"}, "tester@fixture.invalid"),
])
def test_wrapper_uses_oci_destination(remote, overrides, destination):
    remote.update(overrides)
    result = run(remote, "dev", "t")
    assert result.returncode == 0, result.stderr
    args = ssh_args(remote)
    destination_index = len(args) - 2
    assert args[-2] == destination
    option_indices = [index for index, argument in enumerate(args) if argument == "-o"]
    assert option_indices
    assert all(index + 1 < destination_index for index in option_indices)
    assert "BatchMode=yes" in args
    assert "ConnectTimeout=15" in args
    assert "ServerAliveInterval=15" in args
    assert "ServerAliveCountMax=4" in args


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_wrapper_builds_remote_command(remote, environment):
    result = run(remote, environment, "t")
    assert result.returncode == 0, result.stderr
    command = ssh_args(remote)[-1]
    assert "sudo env ACX_OCI_BIN=/home/ubuntu/.oci-venv/bin/oci python3 -B" in command
    for token in ("mktemp -d", "trap", "EXIT", "rm -rf", "tar",
                  "python3 -B",
                  "/scripts/env/render_env.py", "materialize", "--root",
                  "/config/env", "--env", environment, "--target", "t", "--into",
                  f"/opt/acx-backend/{environment}/.env"):
        assert token in command


def test_wrapper_passes_oci_cli_override_to_remote_command(remote, tmp_path):
    cli_bin = tmp_path / "oci-venv" / "bin" / "oci"
    remote["ENV_MATERIALIZE_OCI_BIN"] = str(cli_bin)

    result = run(remote, "dev", "t")

    assert result.returncode == 0, result.stderr
    command = ssh_args(remote)[-1]
    assert f"sudo env ACX_OCI_BIN={cli_bin} python3 -B" in command


@pytest.mark.parametrize("cli_bin", [
    "relative/oci",
    "/tmp/../oci",
    "/tmp/invalid path/oci",
    "/tmp/oci;whoami",
])
def test_wrapper_refuses_invalid_oci_cli_override_before_ssh(remote, cli_bin):
    remote["ENV_MATERIALIZE_OCI_BIN"] = cli_bin

    result = run(remote, "dev", "t")

    no_ssh(remote)
    assert result.returncode == 2
    assert "ENV_MATERIALIZE_OCI_BIN" in result.stderr


def test_wrapper_streams_code_and_fixture_manifest(remote):
    result = run(remote, "dev", "t")
    assert result.returncode == 0, result.stderr
    ssh_args(remote)
    with Path(remote["SHIM_STDIN"]).open("rb") as stream:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            files = {}
            for member in archive:
                if member.isfile():
                    files[member.name.removeprefix("./")] = archive.extractfile(member).read()
    for name in ("scripts/env/render_env.py", "scripts/env/materialize.py",
                 "config/env/manifest.d/targets.toml", "config/env/manifest.d/10-remote.toml"):
        assert name in files
    for name in ("targets.toml", "10-remote.toml"):
        assert files[f"config/env/manifest.d/{name}"] == (
            Path(remote["ENV_MANIFEST_ROOT"]) / "manifest.d" / name).read_bytes()
    assert all(SECRET.encode() not in data for data in files.values())


@pytest.mark.parametrize("args", [[], ["dev"], ["dev", "t", "--unknown"],
                                    ["dev", "t", "--adopt"]])
def test_wrapper_refuses_invalid_usage(remote, args):
    result = run(remote, *args)
    no_ssh(remote)
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()


@pytest.mark.parametrize("environment,target", [("staging", "t"), ("dev", "missing-target")])
def test_wrapper_refuses_missing_remote_path(remote, environment, target):
    result = run(remote, environment, target)
    no_ssh(remote)
    assert result.returncode == 2
    assert (environment if environment == "staging" else target) in result.stderr


def test_wrapper_refuses_target_without_remote_paths(remote):
    manifest = Path(remote["ENV_MANIFEST_ROOT"]) / "manifest.d"
    targets = manifest / "targets.toml"
    targets.write_text("\n".join(line for line in targets.read_text().splitlines()
                                 if "remote_paths" not in line))
    fragment = manifest / "10-remote.toml"
    fragment.write_text(fragment.read_text().replace("host:", "env:PGPASSWORD"))
    result = run(remote, "dev", "t")
    no_ssh(remote)
    assert result.returncode == 2
    assert "dev" in result.stderr


@pytest.mark.parametrize("code", [4, 75])
def test_wrapper_propagates_ssh_exit_code(remote, code):
    remote["SHIM_RC"] = str(code)
    result = run(remote, "dev", "t")
    assert result.returncode == code
    ssh_args(remote)


@pytest.mark.parametrize("settings,check,adopt", [
    (["ENV=dev"], True, False), (["ENV=dev", "APPLY=1"], False, False),
    (["ENV=dev", "APPLY=1", "ADOPT=1"], False, True),
    (["ENV=prod"], True, False),
    (["ENV=prod", "APPLY=1", "CONFIRM=prod"], False, False),
])
def test_make_forwards_materialize_mode(remote, settings, check, adopt):
    result = run(remote, "TARGET=t", *settings, make=True)
    assert result.returncode == 0, result.stderr
    command = ssh_args(remote)[-1]
    assert ("--check" in command) == check
    assert ("--adopt" in command) == adopt


@pytest.mark.parametrize("settings", [
    ["ENV=dev", "TARGET=t", "ADOPT=1"],
    ["ENV=prod", "TARGET=t", "APPLY=1"],
    ["ENV=prod", "TARGET=t", "APPLY=1", "CONFIRM=dev"],
])
def test_make_refuses_unsafe_apply(remote, settings):
    result = run(remote, *settings, make=True)
    no_ssh(remote)
    assert result.returncode != 0
    # An absent make target is not evidence that its safety gate works.
    assert "No rule to make target" not in result.stderr


@pytest.mark.parametrize("settings", [[], ["ENV=dev"], ["TARGET=t"]])
def test_make_requires_env_and_target(remote, settings):
    result = run(remote, *settings, make=True)
    no_ssh(remote)
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
