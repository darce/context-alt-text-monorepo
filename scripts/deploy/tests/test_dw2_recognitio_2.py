"""Regressions for recognition deploy lease and diagnostics fixes."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"


def _run_shell(tmp_path: Path, statements: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    command = f"source {shlex.quote(str(SCRIPT))}\n{statements}\n"
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", command],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


def _run_lease(tmp_path: Path, ttl: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8")
    sudo.chmod(0o755)
    statements = f'''
GREEN=; YELLOW=; RED=; RESET=
export PATH={shlex.quote(str(bin_dir))}:$PATH
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ bash -c "${{@: -1}}"; }}
ACX_DEPLOY_BACKUP_ROOT={shlex.quote(str(tmp_path / "vm-backups"))}
deploy_env_lease acquire dev
'''
    return _run_shell(
        tmp_path,
        statements,
        ACX_DEPLOY_TRANSACTION_ID="dw2-transaction",
        ACX_DEPLOY_LOCK_TTL_SECONDS=ttl,
        ACX_PUSH_TIMEOUT="1000",
        ACX_PULL_TIMEOUT="1000",
        ACX_REMOTE_COMMAND_TIMEOUT="7",
        ACX_GPU_SNAPSHOT_GATE_TIMEOUT_SECONDS="11",
        ACX_CUTOVER_HEALTH_ATTEMPTS="2",
        ACX_CUTOVER_HEALTH_SLEEP="0",
        ACX_CANONICAL_HEALTH_ATTEMPTS="3",
        ACX_CANONICAL_HEALTH_SLEEP="0",
        ACX_VERIFY_ATTEMPTS="1",
        ACX_VERIFY_SLEEP="0",
        ACX_GPU_SNAPSHOT_GATE_ATTEMPTS="4",
        ACX_GPU_SNAPSHOT_GATE_SLEEP="0",
    )


def test_lease_ttl_covers_restart_probes_and_gpu_gate_timeouts(tmp_path: Path) -> None:
    below = _run_lease(tmp_path / "below", "3392")
    assert below.returncode != 0, below.stdout + below.stderr
    assert "3393" in below.stdout + below.stderr

    exact = _run_lease(tmp_path / "exact", "3393")
    assert exact.returncode == 0, exact.stdout + exact.stderr


def test_model_preflight_sanitizes_combined_ssh_diagnostic(tmp_path: Path) -> None:
    result = _run_shell(
        tmp_path,
        r'''
GREEN=; YELLOW=; RED=; RESET=
assert_remote_env_image_tag() { :; }
env_to_remote_dir() { printf '/srv/recognition'; }
_remote_dotenv_value() {
  case "$2" in
    RECOGNITION_FACE_PIPELINE_MODELS_DIR) printf '/data/cache/models' ;;
    ACX_MODELS_PATH) printf '/srv/models' ;;
  esac
}
ssh() {
  printf 'DIR_FAIL:/data/cache/models\n'
  printf 'Authorization: BEARER leaked-harm-secret\033[31mremote text\n' >&2
  return 1
}
preflight_remote_face_pipeline_models dev-fir
''',
    )

    diagnostic = result.stdout + result.stderr
    assert result.returncode != 0
    assert "leaked-harm-secret" not in diagnostic
    assert "\x1b" not in diagnostic
    assert "diagnostic:" in diagnostic


def test_sanitizer_works_without_gnu_sed_case_insensitive_flag(tmp_path: Path) -> None:
    sed = shutil.which("sed")
    assert sed is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    wrapper = bin_dir / "sed"
    wrapper.write_text(
        f'''#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in *gI*) echo 'BSD sed: invalid substitution flag' >&2; exit 2 ;; esac
done
exec {shlex.quote(sed)} "$@"
''',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("sanitize_deploy_diagnostic() {")
    end = source.index("\n}\n", start) + 2
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(
        ["bash", "-c", source[start:end] + "\nprintf '%s\\n' 'Authorization: BEARER leaked-sed-secret' | sanitize_deploy_diagnostic"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "leaked-sed-secret" not in result.stdout
    assert "[REDACTED]" in result.stdout
    assert result.stdout.startswith("diagnostic: ")
