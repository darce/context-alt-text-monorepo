"""Cutover recovery safety: missing-candidate abort and inflight probe protocol.

Finding 13676 / RES-03: abort_cutover_candidate's remote payload `set -e` plus
unconditional `systemctl stop` fails when the next unit is absent, so rollback
never reaches sticky-repo restore.
Finding 13677 / RES-02: cutover_inflight_present returns raw `sudo test -f` rc;
recover_interrupted_cutover and recover_persisted_cutover `|| return 0` treat
timeout/auth/transport as confirmed absence (RLSE-03, DATA-13, TEST-15, AGT-06).
TEST-15: raw SSH/run_with_deadline rc 1 with no PRESENT/ABSENT token must not
be classified as confirmed absence (inject transport_one).
MCP10415 / RLSE-03 / RES-03: abort must not treat systemctl stop rc 5 as
confirmed not-found. systemd 255.4-1ubuntu8.14 `systemctl show UNIT
--property=LoadState --property=ActiveState --property=SubState --no-pager`
returns LoadState=not-found ActiveState=inactive SubState=dead (exit 0).
Loaded/active + stop rc 5 must refuse unit removal and compose cleanup.
State query failure/empty/malformed/unknown must not permit failed-stop
cleanup. TEST-15.

Sandbox isolation: every mutation is under pytest tmp_path. `/etc/systemd/system`
is rewritten to a tmp unit dir. sudo/systemctl/docker/rm are fail-closed shims.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"
SYSTEMD_UNIT_DIR = "/etc/systemd/system"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _install_fail_closed_shims(
    tmp_path: Path,
    *,
    fail_at: str | None = None,
    sudo_fail: bool = False,
    show_mode: str | None = None,
) -> Path:
    """Install sudo/systemctl/docker shims that cannot touch paths outside tmp_path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    records = tmp_path / "shim.log"
    state = tmp_path / "unit-state"
    state.mkdir(exist_ok=True)
    allowed = tmp_path.resolve()
    _write_executable(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"allowed='{allowed}'\n"
        f"records='{records}'\n"
        f"sudo_fail={'1' if sudo_fail else '0'}\n"
        f"fail_at='{fail_at or ''}'\n"
        "if [[ \"$sudo_fail\" == 1 ]]; then echo 'sudo: a password is required' >&2; exit 1; fi\n"
        "under_allowed() {\n"
        "  local raw=\"$1\" abs prefix\n"
        "  [[ \"$raw\" == /* ]] || raw=\"$PWD/$raw\"\n"
        "  abs=\"$(realpath -m -- \"$raw\")\"\n"
        "  prefix=\"$allowed/\"\n"
        "  [[ \"$abs\" == \"$allowed\" || \"$abs\" == \"$prefix\"* ]]\n"
        "}\n"
        "cmd=\"${1:-}\"; shift || true\n"
        "printf 'sudo %s %s\\n' \"$cmd\" \"$*\" >>\"$records\"\n"
        "case \"$cmd\" in\n"
        "  systemctl|docker)\n"
        "    exec \"$cmd\" \"$@\"\n"
        "    ;;\n"
        "  python3)\n"
        "    [[ \"$1\" == -c && \"$#\" == 3 ]] || exit 2\n"
        "    under_allowed \"$3\" || exit 2\n"
        "    exec python3 \"$@\"\n"
        "    ;;\n"
        "  test)\n"
        "    for arg in \"$@\"; do\n"
        "      # POSIX test operators are not paths: unary -f/-d/..., negation `!`.\n"
        "      [[ \"$arg\" == -* || \"$arg\" == '!' ]] && continue\n"
        "      under_allowed \"$arg\" || { echo \"sudo test: path outside sandbox: $arg\" >&2; exit 2; }\n"
        "    done\n"
        "    exec test \"$@\"\n"
        "    ;;\n"
        "  rm)\n"
        "    if [[ \"$fail_at\" == unit-rm ]]; then echo 'rm failed' >&2; exit 1; fi\n"
        "    for arg in \"$@\"; do\n"
        "      [[ \"$arg\" == -* ]] && continue\n"
        "      under_allowed \"$arg\" || { echo \"sudo rm: path outside sandbox: $arg\" >&2; exit 2; }\n"
        "    done\n"
        "    exec rm \"$@\"\n"
        "    ;;\n"
        "  *)\n"
        "    echo \"sudo: refused unexpected command: ${cmd:-empty}\" >&2\n"
        "    exit 2\n"
        "    ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "systemctl",
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"state='{state}'\n"
        f"records='{records}'\n"
        f"fail_at='{fail_at or ''}'\n"
        f"show_mode='{show_mode or ''}'\n"
        "cmd=\"${1:-}\"; shift || true\n"
        "printf 'systemctl %s %s\\n' \"$cmd\" \"$*\" >>\"$records\"\n"
        "unit=\"${1:-}\"\n"
        "unit=\"${unit#\\'}\"\n"
        "unit=\"${unit%\\'}\"\n"
        "unit=\"${unit%.service}\"\n"
        "case \"$cmd\" in\n"
        "  stop)\n"
        "    if [[ \"$fail_at\" == stop ]]; then echo 'stop failed' >&2; exit 1; fi\n"
        "    if [[ \"$fail_at\" == stop-5 ]]; then echo \"Failed to stop $unit.service.\" >&2; exit 5; fi\n"
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
        "  show)\n"
        "    unit=\"\"; have_load=0; have_active=0; have_sub=0; have_pager=0\n"
        "    for arg in \"$@\"; do\n"
        "      arg=\"${arg#\\'}\"; arg=\"${arg%\\'}\"\n"
        "      case \"$arg\" in\n"
        "        --no-pager) have_pager=1 ;;\n"
        "        --property=LoadState) have_load=1 ;;\n"
        "        --property=ActiveState) have_active=1 ;;\n"
        "        --property=SubState) have_sub=1 ;;\n"
        "        --property=*|--*)\n"
        "          echo \"systemctl: refused unsupported show flag: $arg\" >&2\n"
        "          exit 2\n"
        "          ;;\n"
        "        *) unit=\"$arg\" ;;\n"
        "      esac\n"
        "    done\n"
        "    unit=\"${unit%.service}\"\n"
        "    if [[ \"$have_pager\" != 1 || \"$have_load\" != 1 || \"$have_active\" != 1 || \"$have_sub\" != 1 || -z \"$unit\" ]]; then\n"
        "      echo 'systemctl: refused show without LoadState,ActiveState,SubState and --no-pager' >&2\n"
        "      exit 2\n"
        "    fi\n"
        "    if [[ \"$show_mode\" == fail ]]; then echo 'Failed to get properties' >&2; exit 1; fi\n"
        "    if [[ \"$show_mode\" == empty ]]; then exit 0; fi\n"
        "    if [[ \"$show_mode\" == malformed ]]; then printf 'not-a-property-listing\\n'; exit 0; fi\n"
        "    if [[ \"$show_mode\" == unknown ]]; then\n"
        "      printf 'LoadState=unexpected\\nActiveState=unexpected\\nSubState=unexpected\\n'\n"
        "      exit 0\n"
        "    fi\n"
        "    if [[ ! -f \"$state/$unit\" ]]; then\n"
        "      printf 'LoadState=not-found\\nActiveState=inactive\\nSubState=dead\\n'\n"
        "      exit 0\n"
        "    fi\n"
        "    active_state=\"$(cat \"$state/$unit\")\"\n"
        "    if [[ \"$active_state\" == active ]]; then\n"
        "      printf 'LoadState=loaded\\nActiveState=active\\nSubState=running\\n'\n"
        "    else\n"
        "      printf 'LoadState=loaded\\nActiveState=inactive\\nSubState=dead\\n'\n"
        "    fi\n"
        "    exit 0\n"
        "    ;;\n"
        "  *)\n"
        "    echo \"systemctl: refused unsupported command: ${cmd:-empty}\" >&2\n"
        "    exit 2\n"
        "    ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"records='{records}'\n"
        f"fail_at='{fail_at or ''}'\n"
        "printf 'docker %s\\n' \"$*\" >>\"$records\"\n"
        "if [[ \"$1\" != compose ]]; then echo 'docker: refused unexpected command' >&2; exit 2; fi\n"
        "if [[ \"$fail_at\" == compose-rm ]]; then echo 'compose rm failed' >&2; exit 1; fi\n"
        "exit 0\n",
    )
    return bin_dir


def _capture_abort_payload(tmp_path: Path, env: str = "dev") -> str:
    payload = tmp_path / "abort.payload.raw"
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


def _sandbox_abort_payload(tmp_path: Path, env: str = "dev") -> str:
    """Rewrite host paths in the captured payload onto tmp_path descendants."""
    payload = _capture_abort_payload(tmp_path, env)
    remote = tmp_path / "remote"
    systemd = tmp_path / "systemd"
    remote.mkdir(exist_ok=True)
    systemd.mkdir(exist_ok=True)
    payload = payload.replace("/opt/acx-backend/dev", str(remote))
    payload = payload.replace(f"/opt/acx-backend/{env}", str(remote))
    payload = payload.replace(SYSTEMD_UNIT_DIR, str(systemd))
    (tmp_path / "abort.payload").write_text(payload, encoding="utf-8")
    return payload


def _run_abort_payload(
    tmp_path: Path,
    *,
    unit_state: str,
    fail_at: str | None = None,
    show_mode: str | None = None,
    env: str = "dev",
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Execute the captured remote abort payload with fail-closed local shims."""
    _sandbox_abort_payload(tmp_path, env)
    bin_dir = _install_fail_closed_shims(tmp_path, fail_at=fail_at, show_mode=show_mode)
    state = tmp_path / "unit-state"
    unit = f"acx-{env}-next"
    if unit_state in ("active", "inactive"):
        (state / unit).write_text(unit_state, encoding="utf-8")
        (state / f"{unit}.enabled").write_text("1", encoding="utf-8")
        (tmp_path / "systemd" / f"{unit}.service").write_text("# fake unit\n", encoding="utf-8")
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
    records = tmp_path / "shim.log"
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
    assert not (tmp_path / "systemd" / "acx-dev-next.service").exists()


@pytest.mark.parametrize("fail_at", ["stop", "compose-rm", "daemon-reload", "unit-rm"])
def test_abort_payload_propagates_genuine_cleanup_failure(tmp_path: Path, fail_at: str) -> None:
    result, logged = _run_abort_payload(tmp_path, unit_state="active", fail_at=fail_at)
    combined = result.stdout + result.stderr + logged
    assert result.returncode != 0, combined
    if fail_at == "stop":
        assert (tmp_path / "systemd" / "acx-dev-next.service").exists(), combined
        assert "systemctl disable acx-dev-next" not in logged, combined
        assert "sudo rm" not in logged, combined
        assert "docker compose" not in logged, combined


def _assert_failed_stop_did_not_cleanup(
    tmp_path: Path, result: subprocess.CompletedProcess[str], logged: str
) -> None:
    combined = result.stdout + result.stderr + logged
    assert result.returncode != 0, combined
    assert (tmp_path / "systemd" / "acx-dev-next.service").exists(), combined
    assert "compose" not in logged, combined


def test_abort_refuses_cleanup_when_loaded_active_stop_returns_5(tmp_path: Path) -> None:
    """Stop rc 5 on a loaded/active unit is not confirmed not-found (MCP10415)."""
    result, logged = _run_abort_payload(tmp_path, unit_state="active", fail_at="stop-5")
    _assert_failed_stop_did_not_cleanup(tmp_path, result, logged)


def test_abort_cleans_up_when_show_reports_not_found(tmp_path: Path) -> None:
    """Confirmed LoadState=not-found may clean up even if stop exits 5."""
    result, logged = _run_abort_payload(tmp_path, unit_state="absent", fail_at="stop-5")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined
    assert "compose" in logged and "rm" in logged


@pytest.mark.parametrize("show_mode", ["fail", "empty", "malformed", "unknown"])
def test_abort_refuses_cleanup_when_state_query_is_unconfirmed(
    tmp_path: Path, show_mode: str
) -> None:
    result, logged = _run_abort_payload(
        tmp_path, unit_state="active", fail_at="stop-5", show_mode=show_mode
    )
    _assert_failed_stop_did_not_cleanup(tmp_path, result, logged)


def test_systemctl_show_emits_vm_not_found_shape(tmp_path: Path) -> None:
    bin_dir = _install_fail_closed_shims(tmp_path)
    env_vars = os.environ.copy()
    env_vars["PATH"] = f"{bin_dir}:{env_vars.get('PATH', '')}"
    result = subprocess.run(
        [
            "systemctl",
            "show",
            "acx-prod-next.service",
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
            "--no-pager",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env_vars,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "LoadState=not-found",
        "ActiveState=inactive",
        "SubState=dead",
    ]


def test_systemctl_show_refuses_weaker_query(tmp_path: Path) -> None:
    bin_dir = _install_fail_closed_shims(tmp_path)
    env_vars = os.environ.copy()
    env_vars["PATH"] = f"{bin_dir}:{env_vars.get('PATH', '')}"
    result = subprocess.run(
        ["systemctl", "show", "acx-prod-next.service"],
        text=True,
        capture_output=True,
        check=False,
        env=env_vars,
        cwd=tmp_path,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "refused" in result.stderr


def test_sudo_shim_rejects_outside_paths_without_mutation(tmp_path: Path) -> None:
    bin_dir = _install_fail_closed_shims(tmp_path)
    env_vars = os.environ.copy()
    env_vars["PATH"] = f"{bin_dir}:{env_vars.get('PATH', '')}"
    host_unit = f"{SYSTEMD_UNIT_DIR}/acx-dev-next.service"
    result = subprocess.run(
        ["sudo", "rm", "-f", host_unit],
        text=True,
        capture_output=True,
        check=False,
        env=env_vars,
        cwd=tmp_path,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "outside sandbox" in result.stderr
    log = (tmp_path / "shim.log").read_text(encoding="utf-8")
    assert host_unit in log
    assert "sudo rm" in log


def test_sudo_shim_rejects_unexpected_commands(tmp_path: Path) -> None:
    bin_dir = _install_fail_closed_shims(tmp_path)
    env_vars = os.environ.copy()
    env_vars["PATH"] = f"{bin_dir}:{env_vars.get('PATH', '')}"
    result = subprocess.run(
        ["sudo", "systemctl", "cat", "acx-dev-next"],
        text=True,
        capture_output=True,
        check=False,
        env=env_vars,
        cwd=tmp_path,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "unsupported command" in result.stderr
    result = subprocess.run(
        ["sudo", "bash", "-c", "echo pwned"],
        text=True,
        capture_output=True,
        check=False,
        env=env_vars,
        cwd=tmp_path,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "unexpected command" in result.stderr


def test_absent_candidate_abort_allows_sticky_repo_restore(tmp_path: Path) -> None:
    """do_deploy rollback only restores sticky repo after abort succeeds (13676)."""
    records = tmp_path / "caller.log"
    remote = tmp_path / "remote"
    systemd = tmp_path / "systemd"
    remote.mkdir()
    systemd.mkdir()
    bin_dir = _install_fail_closed_shims(tmp_path)
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export PATH="{bin_dir}:$PATH"
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  last="${{@: -1}}"
  last="${{last//\\/opt\\/acx-backend\\/dev/{remote}}}"
  last="${{last//\\/etc\\/systemd\\/system/{systemd}}}"
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
    bin_dir = _install_fail_closed_shims(tmp_path, sudo_fail=(inject == "sudo_fail"))
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export PATH="{bin_dir}:$PATH"
ACX_DEPLOY_BACKUP_ROOT="{tmp_path}"
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=0
ACX_CUTOVER_COMMITTED=0
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  case "{inject}" in
    transport) return 255 ;;
    transport_one) return 1 ;;
    timeout) return 124 ;;
    generic) return 2 ;;
    malformed) printf 'not-a-token\\n'; return 0 ;;
    empty) return 0 ;;
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


def test_inflight_probe_rejects_malformed_marker_output(tmp_path: Path) -> None:
    result, logged = _run_inflight_callers(
        tmp_path,
        inject="malformed",
        marker=True,
        caller="cutover_inflight_present dev",
    )
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 2, combined


def test_failed_cleanup_is_retried_after_transient_stop_failure(tmp_path: Path) -> None:
    """A later invocation can finish cleanup after a transient stop failure."""
    _sandbox_abort_payload(tmp_path)
    state = tmp_path / "unit-state"
    unit = "acx-dev-next"
    state.mkdir()
    (state / unit).write_text("active\n", encoding="utf-8")
    (state / f"{unit}.enabled").write_text("1", encoding="utf-8")
    unit_file = tmp_path / "systemd" / f"{unit}.service"
    unit_file.write_text("# fake unit\n", encoding="utf-8")

    def run_payload(fail_at: str | None) -> subprocess.CompletedProcess[str]:
        bin_dir = _install_fail_closed_shims(tmp_path, fail_at=fail_at)
        env_vars = os.environ.copy()
        env_vars["PATH"] = f"{bin_dir}:{env_vars.get('PATH', '')}"
        return subprocess.run(
            ["bash", str(tmp_path / "abort.payload")],
            text=True,
            capture_output=True,
            check=False,
            env=env_vars,
            cwd=tmp_path,
        )

    first = run_payload("stop")
    first_logged = (tmp_path / "shim.log").read_text(encoding="utf-8")
    first_combined = first.stdout + first.stderr + first_logged
    assert first.returncode != 0, first_combined
    assert unit_file.exists(), first_combined
    assert "systemctl disable" not in first_logged, first_combined
    assert "docker compose" not in first_logged, first_combined

    second = run_payload(None)
    second_logged = (tmp_path / "shim.log").read_text(encoding="utf-8")
    second_combined = second.stdout + second.stderr + second_logged
    assert second.returncode == 0, second_combined
    assert not unit_file.exists(), second_combined
    assert "systemctl disable acx-dev-next" in second_logged, second_combined
    assert "docker compose" in second_logged, second_combined


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
@pytest.mark.parametrize(
    "inject",
    [
        "transport",
        "transport_one",
        "timeout",
        "generic",
        "sudo_fail",
        "malformed",
        "empty",
    ],
)
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
