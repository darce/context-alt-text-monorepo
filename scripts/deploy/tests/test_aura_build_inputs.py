"""D3 build producer tests: execute both maintained builders, then consume the real identity writer."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from test_bounded_remote_build import FAKE_DOCKER
from test_deploy_snapshot import _git, _repo

from conftest import _write_executable

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/recognition-service.sh"
LIB = ROOT / "scripts/deploy/lib/bounded-remote-build.sh"


def run_shell(body, env=None):
    return subprocess.run(["bash", "-c", body], env=env, text=True, capture_output=True, timeout=30)


def build_fixture(tmp_path):
    repo, _ = _repo(tmp_path)
    service = repo / "apps/prototype-description-service"
    (service / "uv.lock").write_text("version = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--allow-empty", "-qm", "lock input")
    sha = _git(repo, "rev-parse", "HEAD")
    return repo, service, sha


def build_args(argv):
    return dict(argv[i + 1].split("=", 1) for i, value in enumerate(argv) if value == "--build-arg")


def test_local_build_supplies_complete_consumer_identity(tmp_path):
    repo, service, sha = build_fixture(tmp_path)
    record = tmp_path / "argv.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "docker",
        "#!/usr/bin/env python3\nimport json,os,sys\njson.dump(sys.argv[1:],open(os.environ['ARG_RECORD'],'w'))\n",
    )
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", ARG_RECORD=str(record))
    body = f"source {shlex.quote(str(SCRIPT))}\nREPO_ROOT={shlex.quote(str(repo))}\nSERVICE_DIR={shlex.quote(str(service))}\npreflight_docker() {{ :; }}\ndo_build dev\n"
    result = run_shell(body, env)
    assert result.returncode == 0, result.stdout + result.stderr
    args = build_args(json.loads(record.read_text()))
    required = {
        "GIT_COMMIT_SHA",
        "SOURCE_TREE",
        "BUILD_CONTEXT_MANIFEST_SHA256",
        "SERVICE_LOCK_SHA256",
        "BUILD_TIME",
        "SOURCE_INPUTS_JSON",
    }
    assert required <= args.keys(), args
    inputs = json.loads(args["SOURCE_INPUTS_JSON"])
    assert inputs["source_git_sha"] == sha
    assert inputs["source_tree"] == _git(repo, "rev-parse", f"{sha}^{{tree}}")
    assert inputs["source_clean"] is True
    assert inputs["source_scope"] == ["apps/prototype-description-service"]
    assert len(inputs["source_diff_sha256"]) == 64
    name = "d3_real_source_identity"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "apps/prototype-description-service/shared/source_identity.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    output = tmp_path / "identity.json"
    identity = module.write_build_source_identity(
        output=output,
        source_git_sha=args["GIT_COMMIT_SHA"],
        source_tree=args["SOURCE_TREE"],
        build_context_manifest_sha256=args["BUILD_CONTEXT_MANIFEST_SHA256"],
        service_lock_sha256=args["SERVICE_LOCK_SHA256"],
        image_variant="recognition",
        build_time=args["BUILD_TIME"],
    )
    assert module.load_baked_source_identity(output) == identity


def test_dirty_build_keeps_diff_scope_and_clean_truthful(tmp_path):
    repo, service, _ = build_fixture(tmp_path)
    (service / "app.txt").write_text("uncommitted\n")
    result = run_shell(
        f'source {shlex.quote(str(SCRIPT))}\nREPO_ROOT={shlex.quote(str(repo))}\nSERVICE_DIR={shlex.quote(str(service))}\npin_deploy_sha\nprepare_build_identity\nprintf "%s\\n" "$ACX_SOURCE_INPUTS_JSON"\n'
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inputs = json.loads(result.stdout.splitlines()[-1])
    assert inputs["source_clean"] is False
    assert inputs["source_diff_sha256"] != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@pytest.mark.parametrize("invalid", ["missing", "invalid-tree", "invalid-inputs"])
def test_remote_program_refuses_incomplete_identity_before_docker(tmp_path, invalid):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "docker.log"
    _write_executable(bin_dir / "docker", '#!/bin/sh\necho called >>"$ARG_RECORD"\nexit 0\n')
    program = run_shell(f"source {shlex.quote(str(LIB))}; bounded_remote_build_program").stdout
    tree = "b" * 40 if invalid != "invalid-tree" else "no-tree"
    extra = [tree, "c" * 64, "d" * 64, "2026-10-17T00:00:00Z", "{}"] if invalid != "missing" else []
    command = [
        "bash",
        "-s",
        "--",
        "builder",
        "node",
        "unix:///var/run/docker.sock",
        "example/image",
        "a" * 40,
        "runtime",
        "9999999999",
        str(tmp_path),
        *extra,
    ]
    result = subprocess.run(
        command,
        input=program,
        env=dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", ARG_RECORD=str(record)),
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert not record.exists(), "invalid build identity reached Docker"


def test_conditional_local_build_does_not_mask_docker_failure(tmp_path):
    repo, service, _ = build_fixture(tmp_path)
    binary = tmp_path / "bin"
    binary.mkdir()
    _write_executable(binary / "docker", "#!/bin/sh\nexit 37\n")
    variables = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}")
    result = run_shell(
        f"""source {shlex.quote(str(SCRIPT))}
REPO_ROOT={shlex.quote(str(repo))}
SERVICE_DIR={shlex.quote(str(service))}
preflight_docker() {{ :; }}
if do_build dev; then echo FALSE_GREEN; else echo "REFUSED $?"; fi
""",
        variables,
    )
    assert "FALSE_GREEN" not in result.stdout, result.stdout + result.stderr
    assert "REFUSED 37" in result.stdout
