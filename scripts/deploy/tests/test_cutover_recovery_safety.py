"""Cutover recovery safety: missing-candidate abort and inflight probe protocol.

Finding 13676 / RES-03: abort_cutover_candidate's remote payload `set -e` plus
unconditional `systemctl stop` fails when the next unit is absent, so rollback
never reaches sticky-repo restore.
Finding 13677 / RES-02: cutover_inflight_present returns raw `sudo test -f` rc;
recover_interrupted_cutover and recover_persisted_cutover `|| return 0` treat
timeout/auth/transport as confirmed absence (RLSE-03, DATA-13, TEST-15, AGT-06).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _capture_abort_payload(tmp_path: Path, env: str = "dev") -> str:
    payload = tmp_path / "abort.payload"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ printf '%s\\n' "${{@: -1}}" >"{payload}"; return 0; }}
abort_cutover_candidate {env}
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    assert payload.is_file(), result.stdout + result.stderr
    return payload.read_text(encoding="utf-8")


def _run_abort_payload(
    tmp_path: Path,
    *,
    unit_state: str,
    fail_at: str | None = None,
    env: str = "dev",
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Execute the captured remote abort payload with local sudo/systemctl/docker shims."""
    payload = _capture_abort_payload(tmp_path, env)
    remote = tmp_path / "remote"
    remote.mkdir(exist_ok=True)
    payload = payload.replace("/opt/acx-backend/dev", str(remote))
    payload = payload.replace(f"/opt/acx-backend/{env}", str(remote))
    (tmp_path / "abort.payload").write_text(payload, encoding="utf-8")
    records = tmp_path / "shim.log"
    state = tmp_path / "unit-state"
    state.mkdir(exist_ok=True)
    unit = f"acx-{env}-next"
    if unit_state in ("active", "inactive"):
        (state / unit).write_text(unit_state, encoding="utf-8")
        (state / f"{unit}.enabled").write_text("1", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_executable(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\nexec \"$@\"\n",
    )
    _write_executable(
        bin_dir / "systemctl",
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"state='{state}'\n"
        f"records='{records}'\n"
        f"fail_at='{fail_at or ''}'\n"
        "cmd=\"${1:-}\"; shift || true\n"
        "unit=\"${1:-}\"\n"
        "unit=\"${unit#\\'}\"\n"
        "unit=\"${unit%\\'}\"\n"
        "printf 'systemctl %s %s\\n' \"$cmd\" \"$unit\" >>\"$records\"\n"
        "case \"$cmd\" in\n"
        "  stop)\n"
        "    if [[ \"$fail_at\" == stop ]]; then echo 'stop failed' >&2; exit 1; fi\n"
        "    if [[ ! -f \"$state/$unit\" ]]; then echo \"Unit $unit not loaded.\" >&2; exit 5; fi\n"
        "    printf 'inactive\\n' >\"$state/$unit\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  is-enabled)\n"
        "    [[ -f \"$state/$unit.enabled\" ]] && exit 0\n"
        "    exit 1\n"
        "    ;;\n"
        "  disable)\n"
        "    rm -f \"$state/$unit.enabled\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  daemon-reload)\n"
        "    if [[ \"$fail_at\" == daemon-reload ]]; then echo 'reload failed' >&2; exit 1; fi\n"
        "    printf 'reloaded\\n' >>\"$records\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"records='{records}'\n"
        f"fail_at='{fail_at or ''}'\n"
        "printf 'docker %s\\n' \"$*\" >>\"$records\"\n"
        "if [[ \"$fail_at\" == compose-rm ]]; then echo 'compose rm failed' >&2; exit 1; fi\n"
        "exit 0\n",
    )
    env_vars = os.environ.copy()
    env_vars["PATH"] = f"{bin_dir}:{env_vars.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(tmp_path / "abort.payload")],
        text=True,
        capture_output=True,
        check=False,
        env=env_vars,
        cwd=tmp_path,
    )
    logged = records.read_text(encoding="utf-8") if records.exists() else ""
    return result, logged


def test_abort_payload_succeeds_when_candidate_unit_is_absent(tmp_path: Path) -> None:
    result, logged = _run_abort_payload(tmp_path, unit_state="absent")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined
    assert "compose" in logged and "rm" in logged


def test_abort_payload_succeeds_when_candidate_unit_is_inactive(tmp_path: Path) -> None:
    result, logged = _run_abort_payload(tmp_path, unit_state="inactive")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined
    assert "systemctl stop" in logged
    assert "compose" in logged


def test_abort_payload_drains_active_candidate(tmp_path: Path) -> None:
    result, logged = _run_abort_payload(tmp_path, unit_state="active")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined
    assert "systemctl stop acx-dev-next" in logged
    assert "systemctl disable acx-dev-next" in logged
    assert "daemon-reload" in logged
    assert "docker compose" in logged or "compose" in logged
    assert "rm" in logged


@pytest.mark.parametrize("fail_at", ["stop", "compose-rm", "daemon-reload"])
def test_abort_payload_propagates_genuine_cleanup_failure(tmp_path: Path, fail_at: str) -> None:
    result, logged = _run_abort_payload(tmp_path, unit_state="active", fail_at=fail_at)
    combined = result.stdout + result.stderr + logged
    assert result.returncode != 0, combined


def test_absent_candidate_abort_allows_sticky_repo_restore(tmp_path: Path) -> None:
    """do_deploy rollback only restores sticky repo after abort succeeds (13676)."""
    records = tmp_path / "caller.log"
    remote = tmp_path / "remote"
    remote.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "sudo", "#!/usr/bin/env bash\nexec \"$@\"\n")
    _write_executable(
        bin_dir / "systemctl",
        "#!/usr/bin/env bash\n"
        "cmd=\"${1:-}\"\n"
        "[[ \"$cmd\" == stop ]] && { echo 'Unit acx-dev-next not loaded.' >&2; exit 5; }\n"
        "exit 0\n",
    )
    _write_executable(bin_dir / "docker", "#!/usr/bin/env bash\nexit 0\n")
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export PATH="{bin_dir}:$PATH"
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  last="${{@: -1}}"
  last="${{last//\\/opt\\/acx-backend\\/dev/{remote}}}"
  bash -c "$last"
}}
restore_topology_backups() {{ return 0; }}
restore_edge_backups() {{ ACX_TRAFFIC_FLIPPED=0; return 0; }}
restore_prior_image_repo_env() {{ printf 'sticky\\n' >>"{records}"; return 0; }}
if restore_runtime_and_edge dev 0; then
  restore_prior_image_repo_env
fi
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "sticky" in logged.splitlines(), combined


def _run_inflight_callers(
    tmp_path: Path,
    *,
    inject: str,
    marker: bool,
    caller: str,
) -> tuple[subprocess.CompletedProcess[str], str]:
    records = tmp_path / "caller.log"
    inflight_dir = tmp_path / "dev"
    inflight_dir.mkdir(exist_ok=True)
    inflight = inflight_dir / "cutover-inflight"
    if marker:
        inflight.write_text("status=traffic_on_next\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_executable(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\n"
        "if [[ \"${SUDO_FAIL:-0}\" == 1 ]]; then echo 'sudo: a password is required' >&2; exit 1; fi\n"
        "exec \"$@\"\n",
    )
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export PATH="{bin_dir}:$PATH"
export SUDO_FAIL={"1" if inject == "sudo_fail" else "0"}
ACX_DEPLOY_BACKUP_ROOT="{tmp_path}"
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=0
ACX_CUTOVER_COMMITTED=0
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  case "{inject}" in
    transport) return 255 ;;
    timeout) return 124 ;;
    generic) return 2 ;;
    *)
      last="${{@: -1}}"
      bash -c "$last"
      ;;
  esac
}}
restore_edge_backups() {{ printf 'restored\\n' >>"{records}"; ACX_TRAFFIC_FLIPPED=0; return 0; }}
commit_cutover_state() {{ printf 'committed\\n' >>"{records}"; return 0; }}
abort_cutover_candidate() {{ printf 'drained\\n' >>"{records}"; return 0; }}
enable_cutover_candidate() {{ printf 'enabled\\n' >>"{records}"; return 0; }}
{caller}
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    return result, logged


@pytest.mark.parametrize("caller", ["recover_persisted_cutover dev", "recover_interrupted_cutover"])
def test_inflight_present_recovers_and_may_drain(tmp_path: Path, caller: str) -> None:
    result, logged = _run_inflight_callers(tmp_path, inject="ok", marker=True, caller=caller)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "drained" in logged.splitlines(), logged + combined


@pytest.mark.parametrize("caller", ["recover_persisted_cutover dev", "recover_interrupted_cutover"])
def test_inflight_confirmed_absent_skips_without_drain(tmp_path: Path, caller: str) -> None:
    result, logged = _run_inflight_callers(tmp_path, inject="ok", marker=False, caller=caller)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "drained" not in logged.splitlines()
    assert "enabled" not in logged.splitlines()


@pytest.mark.parametrize("caller", ["recover_persisted_cutover dev", "recover_interrupted_cutover"])
@pytest.mark.parametrize("inject", ["transport", "timeout", "generic", "sudo_fail"])
def test_inflight_probe_errors_refuse_recovery_and_do_not_drain(
    tmp_path: Path, caller: str, inject: str
) -> None:
    result, logged = _run_inflight_callers(
        tmp_path, inject=inject, marker=True, caller=caller
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "drained" not in logged.splitlines()
    assert "enabled" not in logged.splitlines()
