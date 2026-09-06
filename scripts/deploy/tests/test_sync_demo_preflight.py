"""Contract tests for the opt-in demo GPU environment preflight."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"


def _run_sync(tmp_path: Path, *, preflight: str | None = None, fail_preflight: bool = False) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    (bin_dir / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'ssh %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "if [[ \"$*\" == *--check-reaper* ]] && [[ \"${FAIL_PREFLIGHT:-0}\" == 1 ]]; then exit 17; fi\n"
        "if [[ \"$1\" == *bash* || \"$*\" == *' bash -se'* ]]; then cat >/dev/null; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "scp").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'scp %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for shim in (bin_dir / "ssh", bin_dir / "scp"):
        shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PLUGIN_ZIP"] = ""
    env["OCI_HOST"] = "test-host.invalid"
    env["OCI_USER"] = "test-user"
    if preflight is None:
        env.pop("ACX_DEMO_GPU_PREFLIGHT", None)
    else:
        env["ACX_DEMO_GPU_PREFLIGHT"] = preflight
    env["FAIL_PREFLIGHT"] = "1" if fail_preflight else "0"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    return (tmp_path / "commands.log").read_text(encoding="utf-8")


def test_gpu_preflight_runs_once_when_opted_in(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1")

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert log.count("--check-reaper") == 1
    assert "/opt/acx-backend/prod/secrets/.env" in log
    assert "/opt/acx-backend/demo/secrets/.env" in log
    assert log.count("docker-compose.demo.yml") >= 1


def test_gpu_preflight_is_off_by_default(tmp_path: Path) -> None:
    result = _run_sync(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert "--check-reaper" not in log
    assert log.count("docker-compose.demo.yml") >= 1


def test_failed_gpu_preflight_aborts_before_demo_compose_scp(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1", fail_preflight=True)

    assert result.returncode == 4, result.stdout + result.stderr
    assert "GPU environment preflight failed" in result.stderr
    assert "docker-compose.demo.yml" not in _log(tmp_path)
