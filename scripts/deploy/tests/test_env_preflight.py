"""Opt-in remote environment-manifest drift checks before a deploy."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"


def _repo_with_stub(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    stub = repo / "scripts/env/materialize_remote.sh"
    stub.parent.mkdir(parents=True)
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$RECORD_FILE\"\n"
        "if [[ -n \"${ORDER_FILE:-}\" ]]; then printf 'materialize_remote\\n' >> \"$ORDER_FILE\"; fi\n"
        "exit \"${STUB_EXIT:-0}\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return repo, stub


def _run(
    tmp_path: Path, env_name: str, *, enabled: bool | None = True, extra: str = ""
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    repo, _ = _repo_with_stub(tmp_path)
    record_file = tmp_path / "argv.txt"
    setup = "unset ACX_ENV_PREFLIGHT" if enabled is None else f"ACX_ENV_PREFLIGHT={int(enabled)}"
    driver = f"""
set -euo pipefail
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
REPO_ROOT={shlex.quote(str(repo))}
{setup}
{extra}
"""
    result = subprocess.run(
        ["bash", "-c", driver],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "HOME": os.environ.get("HOME", "/tmp"),
            "RECORD_FILE": str(record_file),
            "STUB_EXIT": "0",
            "ORDER_FILE": "",
        },
    )
    return result, record_file, repo


def test_manifest_preflight_is_off_by_default(tmp_path: Path) -> None:
    result, record_file, _ = _run(
        tmp_path,
        "dev",
        enabled=None,
        extra="preflight_env_manifest dev\necho PREFLIGHT_OK",
    )
    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT_OK" in result.stdout
    assert "ACX_ENV_PREFLIGHT is not 1" in result.stdout
    assert not record_file.exists()


@pytest.mark.parametrize(
    ("deploy_env", "manifest_env", "target"),
    [
        ("dev", "dev", "svc-vm"),
        ("staging", "staging", "svc-vm"),
        ("prod", "prod", "svc-vm"),
        ("dev-fir", "fir", "svc-fir"),
    ],
)
def test_manifest_preflight_uses_manifest_env_and_target(
    tmp_path: Path, deploy_env: str, manifest_env: str, target: str
) -> None:
    result, record_file, _ = _run(
        tmp_path,
        deploy_env,
        extra=f"preflight_env_manifest {deploy_env}\necho PREFLIGHT_OK",
    )
    assert result.returncode == 0, result.stderr
    assert "PREFLIGHT_OK" in result.stdout
    assert record_file.read_text(encoding="utf-8").splitlines() == [
        manifest_env,
        target,
        "--check",
    ]


def test_manifest_preflight_rejects_unmapped_deploy_env(tmp_path: Path) -> None:
    result, record_file, _ = _run(
        tmp_path,
        "unknown",
        extra="preflight_env_manifest unknown\necho PREFLIGHT_OK",
    )
    assert result.returncode != 0
    assert "unknown" in result.stdout + result.stderr
    assert "PREFLIGHT_OK" not in result.stdout
    assert not record_file.exists()


def test_manifest_preflight_failure_stops_deploy_before_remote_auth(tmp_path: Path) -> None:
    order_file = tmp_path / "order.txt"
    result, record_file, repo = _run(
        tmp_path,
        "dev",
        extra=f"""
export STUB_EXIT=7
export ORDER_FILE={shlex.quote(str(order_file))}
record() {{ printf '%s\\n' "$1" >> "$ORDER_FILE"; }}
pin_deploy_sha() {{ DEPLOY_SHA=0000000000000000000000000000000000000000; }}
init_deploy_ocir_docker_config() {{ :; }}
preflight_ssh() {{ record preflight_ssh; }}
preflight_remote_face_pipeline_models() {{ record preflight_remote_face_pipeline_models; }}
preflight_git_clean() {{ record preflight_git_clean; }}
preflight_branch_synced() {{ record preflight_branch_synced; }}
preflight_remote_ocir_auth() {{ record preflight_remote_ocir_auth; }}
_ship_selected_env dev aggregate
echo DEPLOY_CONTINUED
""",
    )
    assert result.returncode == 1
    assert "DEPLOY_CONTINUED" not in result.stdout
    assert "preflight_remote_ocir_auth" not in order_file.read_text(encoding="utf-8")
    assert record_file.read_text(encoding="utf-8").splitlines() == [
        "dev",
        "svc-vm",
        "--check",
    ]
    diagnostic = result.stdout + result.stderr
    assert "dev" in diagnostic
    assert f"bash {repo}/scripts/env/materialize_remote.sh dev svc-vm --check" in diagnostic


def test_manifest_preflight_runs_between_branch_sync_and_remote_auth(tmp_path: Path) -> None:
    order_file = tmp_path / "order.txt"
    result, record_file, _ = _run(
        tmp_path,
        "dev",
        extra=f"""
export ORDER_FILE={shlex.quote(str(order_file))}
record() {{ printf '%s\\n' "$1" >> "$ORDER_FILE"; }}
pin_deploy_sha() {{ DEPLOY_SHA=0000000000000000000000000000000000000000; }}
init_deploy_ocir_docker_config() {{ :; }}
preflight_ssh() {{ record preflight_ssh; }}
preflight_remote_face_pipeline_models() {{ record preflight_remote_face_pipeline_models; }}
preflight_git_clean() {{ record preflight_git_clean; }}
preflight_branch_synced() {{ record preflight_branch_synced; }}
preflight_remote_ocir_auth() {{ record preflight_remote_ocir_auth; exit 97; }}
_ship_selected_env dev aggregate
""",
    )
    assert result.returncode == 97, result.stderr
    assert record_file.read_text(encoding="utf-8").splitlines() == [
        "dev",
        "svc-vm",
        "--check",
    ]
    assert order_file.read_text(encoding="utf-8").splitlines() == [
        "preflight_ssh",
        "preflight_remote_face_pipeline_models",
        "preflight_git_clean",
        "preflight_branch_synced",
        "materialize_remote",
        "preflight_remote_ocir_auth",
    ]
