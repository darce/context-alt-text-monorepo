"""Regressions for DEFWAVE-2 recognition deploy hardening."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"


def _sanitize_source() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("sanitize_deploy_diagnostic() {")
    end = source.index("\n}\n", start)
    return source[start : end + 2]


def _sanitize(raw: str) -> str:
    result = subprocess.run(
        ["bash", "-c", _sanitize_source() + "\nsanitize_deploy_diagnostic"],
        input=raw,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("password: |\n  hunter2secretYAML\nother: safe\n", "hunter2secretYAML"),
        ("client_secret: >-\n  hunter2secretFolded\n  still-secret\nnext: safe\n", "hunter2secretFolded"),
        ("client_secret: >-\n  hunter2secretFolded\n  still-secret\nnext: safe\n", "still-secret"),
    ],
)
def test_redacts_yaml_secret_block_contents(raw: str, secret: str) -> None:
    output = _sanitize(raw)
    assert secret not in output, output
    assert "diagnostic: next: safe" in output or "diagnostic: other: safe" in output


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("curl -u acx:hunter2secretCURLU https://example.invalid\n", "hunter2secretCURLU"),
        ("wget --user=acx:hunter2secretWGET https://example.invalid\n", "hunter2secretWGET"),
        ("curl -u 'acx:hunter2 secretCURLSPACE' https://example.invalid\n", "secretCURLSPACE"),
        ('wget --user="acx:hunter2 secretWGETSPACE" https://example.invalid\n', "secretWGETSPACE"),
    ],
)
def test_redacts_curl_and_wget_user_credentials(raw: str, secret: str) -> None:
    output = _sanitize(raw)
    assert secret not in output, output
    assert "[REDACTED]" in output


def test_redacts_unquoted_values_through_whitespace() -> None:
    output = _sanitize('{"SECRET":abc}def "TOKEN":abc,def tail=visible\n')
    assert "}def" not in output, output
    assert ",def" not in output, output
    assert "tail=visible" in output, output


@pytest.mark.parametrize(
    "raw",
    [
        '{\n  "password":\n    "hunter2secretJSON",\n  "safe": "visible"\n}\n',
        '{\n  "password"\n  :\n    "hunter2secretJSON",\n  "safe": "visible"\n}\n',
    ],
)
def test_redacts_json_secret_scalar_on_following_line(raw: str) -> None:
    output = _sanitize(raw)
    assert "hunter2secretJSON" not in output, output
    assert "visible" in output, output


def _render_unit(backend: str) -> str:
    command = f'''
source "{SCRIPT}"
ssh() {{ printf '%s\\n' "{backend}"; }}
render_unit dev
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=True)
    return result.stdout


def test_render_unit_enables_vault_bootstrap_only_for_oci_vault() -> None:
    vault = _render_unit("oci_vault")
    assert "\nExecStartPre=/opt/acx-backend/dev/fetch-vault-bootstrap.sh\n" in vault
    assert "\n# ExecStartPre=/opt/acx-backend/dev/fetch-vault-bootstrap.sh\n" not in vault

    env_backend = _render_unit("env")
    assert "\n# ExecStartPre=/opt/acx-backend/dev/fetch-vault-bootstrap.sh\n" in env_backend


def _run_unit_install(
    tmp_path: Path, backend: str, hook_present: bool
) -> tuple[subprocess.CompletedProcess[str], str, Path]:
    remote_commands = tmp_path / "ssh.log"
    installed_unit = tmp_path / "installed.service"
    command = f'''
source "{SCRIPT}"
REMOTE_COMMANDS="{remote_commands}"
INSTALLED_UNIT="{installed_unit}"
BACKEND="{backend}"
HOOK_PRESENT={1 if hook_present else 0}
ssh() {{
  last="${{@: -1}}"
  printf '%s\\n' "$last" >>"$REMOTE_COMMANDS"
  if [[ "$last" == *"RECOGNITION_SECRET_BACKEND="* ]]; then
    printf '%s\\n' "$BACKEND"
  elif [[ "$last" == test\\ -x\\ * ]]; then
    [[ "$HOOK_PRESENT" == 1 ]]
  elif [[ "$last" == *"cat > '/tmp/acx-dev.service'"* ]]; then
    printf 'unit-install\\n' >>"$REMOTE_COMMANDS"
    cat >"$INSTALLED_UNIT"
  else
    return 91
  fi
}}
install_rendered_unit dev
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = remote_commands.read_text(encoding="utf-8") if remote_commands.exists() else ""
    return result, logged, installed_unit


def test_vault_unit_install_refuses_missing_bootstrap_hook(tmp_path: Path) -> None:
    result, logged, _ = _run_unit_install(tmp_path, "oci_vault", hook_present=False)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "/opt/acx-backend/dev/fetch-vault-bootstrap.sh" in combined, combined
    assert "infra/oci/vault-instance-principal-runbook.md" in combined, combined
    assert "unit-install" not in logged, logged


def test_vault_unit_install_enables_bootstrap_hook_when_present(tmp_path: Path) -> None:
    result, logged, installed_unit = _run_unit_install(tmp_path, "oci_vault", hook_present=True)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "unit-install" in logged, logged
    unit = installed_unit.read_text(encoding="utf-8")
    assert "\nExecStartPre=/opt/acx-backend/dev/fetch-vault-bootstrap.sh\n" in unit


def test_env_unit_install_does_not_probe_vault_hook(tmp_path: Path) -> None:
    result, logged, installed_unit = _run_unit_install(tmp_path, "env", hook_present=False)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "test -x" not in logged, logged
    assert "unit-install" in logged, logged
    unit = installed_unit.read_text(encoding="utf-8")
    assert "\n# ExecStartPre=/opt/acx-backend/dev/fetch-vault-bootstrap.sh\n" in unit


def _sticky_shell(tmp_path: Path, command: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n', encoding="utf-8")
    sudo.chmod(0o755)
    return f'''
source "{SCRIPT}"
export PATH="{bin_dir}:$PATH"
env_to_remote_dir() {{ printf '%s\\n' "{tmp_path}"; }}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ bash -c "${{@: -1}}"; }}
preflight_ssh() {{ :; }}
ACX_DEPLOY_BACKUP_ROOT="{tmp_path}/deploy-backups"
ACX_PRIOR_IMAGE_REPO_ENV=dev
{command}
'''


def _sticky_run(tmp_path: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _sticky_shell(tmp_path, command)],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def _sticky_claim(tmp_path: Path) -> str:
    result = _sticky_run(tmp_path, f'image_repo_resource claim "{tmp_path}" "" ""')
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _sticky_ship(tmp_path: Path, owner: str) -> subprocess.CompletedProcess[str]:
    return _sticky_run(
        tmp_path,
        f'ACX_IMAGE_REPO_OWNER_ID={owner}; ACX_IMAGE_REPO=example.test/shared; ship_remote_image_repo_env "{tmp_path}"',
    )


def test_sticky_env_ship_clamps_mode_to_0600(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\n")
    env_file.chmod(0o644)
    owner = _sticky_claim(tmp_path)

    result = _sticky_ship(tmp_path, owner)

    assert result.returncode == 0, result.stdout + result.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_sticky_env_restore_clamps_mode_to_0600(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\nACX_IMAGE_REPO=example.test/prior\n")
    env_file.chmod(0o644)
    owner = _sticky_claim(tmp_path)
    shipped = _sticky_ship(tmp_path, owner)
    assert shipped.returncode == 0, shipped.stdout + shipped.stderr
    env_file.chmod(0o644)

    result = _sticky_run(tmp_path, f"ACX_IMAGE_REPO_OWNER_ID={owner}; restore_prior_image_repo_env")

    assert result.returncode == 0, result.stdout + result.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
