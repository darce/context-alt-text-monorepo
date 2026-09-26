"""Regression tests for Caddy promotion recovery in sync-demo.sh."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"


def _remote_body(marker: str, remote_dir: Path) -> str:
    script = SCRIPT.read_text(encoding="utf-8")
    section = script.split(marker, 1)[1]
    match = re.search(r"\$SSH bash -se <<'EOF'\n(.*?)\nEOF", section, re.DOTALL)
    assert match is not None, f"could not find remote body after {marker!r}"
    return match.group(1).replace("/opt/acx-backend", str(remote_dir))


def _run_remote_body(
    tmp_path: Path,
    body: str,
    *,
    fail_staged_copy: bool = False,
    fail_container_checksum: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
        "if [[ \"${FAIL_CONTAINER_CHECKSUM:-0}\" == 1 && \"$*\" == *'sha256sum /etc/caddy/Caddyfile'* ]]; then exit 17; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "cat").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${FAIL_STAGED_COPY:-0}\" == 1 && \"$#\" == 1 && \"$1\" == Caddyfile.new ]]; then\n"
        "  printf 'partial replacement'\n"
        "  exit 23\n"
        "fi\n"
        "exec /usr/bin/cat \"$@\"\n",
        encoding="utf-8",
    )
    for shim in (bin_dir / "docker", bin_dir / "cat"):
        shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["DOCKER_LOG"] = str(docker_log)
    env["FAIL_STAGED_COPY"] = "1" if fail_staged_copy else "0"
    env["FAIL_CONTAINER_CHECKSUM"] = "1" if fail_container_checksum else "0"
    result = subprocess.run(
        ["bash", "-se"],
        input=body,
        cwd=tmp_path / "remote",
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""


def test_failed_caddy_copy_restores_the_previous_file(tmp_path: Path) -> None:
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir / "Caddyfile").write_text("previous valid config\n", encoding="utf-8")
    (remote_dir / "Caddyfile.new").write_text("replacement config\n", encoding="utf-8")
    (remote_dir / "docker-compose.caddy.yml.new").write_text("compose config\n", encoding="utf-8")

    result, _ = _run_remote_body(
        tmp_path,
        _remote_body('Validate staged Caddy config, then promote', remote_dir),
        fail_staged_copy=True,
    )

    assert result.returncode != 0
    assert (remote_dir / "Caddyfile").read_text(encoding="utf-8") == "previous valid config\n"


def test_promoted_caddyfile_is_validated_after_the_in_place_copy(tmp_path: Path) -> None:
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir / "Caddyfile").write_text("previous valid config\n", encoding="utf-8")
    (remote_dir / "Caddyfile.new").write_text("replacement config\n", encoding="utf-8")
    (remote_dir / "docker-compose.caddy.yml.new").write_text("compose config\n", encoding="utf-8")

    result, docker_log = _run_remote_body(
        tmp_path,
        _remote_body('Validate staged Caddy config, then promote', remote_dir),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    validations = [line for line in docker_log.splitlines() if "caddy validate" in line]
    assert len(validations) == 2
    assert f"{remote_dir}/Caddyfile:/etc/caddy/Caddyfile:ro" in validations[1]
    assert (remote_dir / "Caddyfile").read_text(encoding="utf-8") == "replacement config\n"


def test_failed_container_checksum_takes_the_force_recreate_path(tmp_path: Path) -> None:
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir / "Caddyfile").write_text("replacement config\n", encoding="utf-8")

    result, docker_log = _run_remote_body(
        tmp_path,
        _remote_body('Recreate Caddy so it joins acx-demo-net', remote_dir),
        fail_container_checksum=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "compose -f docker-compose.caddy.yml up -d --force-recreate caddy" in docker_log
