"""Regressions for deploy state left behind when an interrupted transaction exits."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"


def _run_driver(tmp_path: Path, statements: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = tmp_path / "records.log"
    command = f"""
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
# Isolate compensation decisions/payloads; real ownership is tested with P helper.
recognition_edge_assert_if_active() {{ return 0; }}
recognition_edge_command() {{ run_with_deadline 5 "owned command" ssh "$1"; }}
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
preflight_env_manifest() {{ return 0; }}
deploy_env_lease() {{ return 0; }}
restore_runtime_topology() {{ record restore_runtime_topology "$@"; }}
restore_prior_image_repo_env() {{ record restore_prior_image_repo_env "$@"; }}
restore_env_tag_to_rollback() {{ record restore_env_tag_to_rollback "$@"; return "${{RESTORE_ENV_RC:-0}}"; }}
recover_interrupted_cutover() {{ record recover_interrupted_cutover "$@"; }}
cleanup_remote_build_generation_on_exit() {{ record cleanup_remote_build_generation_on_exit "$@"; }}
_purge_deploy_ocir_docker_config() {{ record _purge_deploy_ocir_docker_config "$@"; }}
_purge_deploy_snapshot() {{ record _purge_deploy_snapshot "$@"; }}
rollback_command_hint() {{ printf 'make deploy-rollback-%s' "$1"; }}
{statements}
"""
    env = os.environ.copy()
    env.update({"RECORDS": str(records), **extra_env})
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, env=env, check=False)
    if records.exists():
        result.records = records.read_text(encoding="utf-8").splitlines()  # type: ignore[attr-defined]
    else:
        result.records = []  # type: ignore[attr-defined]
    return result


def _run_real_driver(tmp_path: Path, statements: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = tmp_path / "records.log"
    command = f"""
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
# Isolate compensation decisions/payloads; real ownership is tested with P helper.
recognition_edge_assert_if_active() {{ return 0; }}
recognition_edge_command() {{ run_with_deadline 5 "owned command" ssh "$1"; }}
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
# Keep real restore orchestration; model only its external admission RPC.
# Native admission/ownership/generation is exercised in test_aura_d5_restore_admission.py.
FIXTURE_ADMISSION_RC=0
recognition_edge_remote() {{
  printf 'recognition_edge_remote' >>"$RECORDS"
  printf ' %q' "$@" >>"$RECORDS"
  printf '\\n' >>"$RECORDS"
  if [[ $# != 3 || ${{1:-}} != admit-runtime || ${{2:-}} != dev ||
        ( ${{3:-}} != current-only && ${{3:-}} != '' ) ]]; then
    printf 'unmodeled compensation admission call\\n' >&2
    return 97
  fi
  return "$FIXTURE_ADMISSION_RC"
}}
deploy_env_lease() {{ return 0; }}
cleanup_remote_build_generation_on_exit() {{ record cleanup_remote_build_generation_on_exit "$@"; }}
_purge_deploy_ocir_docker_config() {{ record _purge_deploy_ocir_docker_config "$@"; }}
_purge_deploy_snapshot() {{ record _purge_deploy_snapshot "$@"; }}
rollback_command_hint() {{ printf 'make deploy-rollback-%s' "$1"; }}
{statements}
"""
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, env=os.environ.copy(), check=False)
    if records.exists():
        result.records = records.read_text(encoding="utf-8").splitlines()  # type: ignore[attr-defined]
    else:
        result.records = []  # type: ignore[attr-defined]
    return result


def _write_lease(path: Path, transaction: str, holder: str, expires_at: int) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        {"transaction": transaction, "holder": holder, "expires_at": expires_at},
        separators=(",", ":"),
    ).encode("ascii")
    path.write_bytes(content)
    return content


def _run_lease_driver(tmp_path: Path, statements: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = tmp_path / "records.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8")
    sudo.chmod(0o755)
    command = f"""
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
# Isolate compensation decisions/payloads; real ownership is tested with P helper.
recognition_edge_assert_if_active() {{ return 0; }}
recognition_edge_command() {{ run_with_deadline 5 "owned command" ssh "$1"; }}
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
preflight_env_manifest() {{ return 0; }}
restore_runtime_topology() {{ record restore_runtime_topology "$@"; }}
restore_prior_image_repo_env() {{ record restore_prior_image_repo_env "$@"; }}
restore_env_tag_to_rollback() {{ record restore_env_tag_to_rollback "$@"; return "${{RESTORE_ENV_RC:-0}}"; }}
recover_interrupted_cutover() {{ record recover_interrupted_cutover "$@"; }}
cleanup_remote_build_generation_on_exit() {{ record cleanup_remote_build_generation_on_exit "$@"; }}
_purge_deploy_ocir_docker_config() {{ record _purge_deploy_ocir_docker_config "$@"; }}
_purge_deploy_snapshot() {{ record _purge_deploy_snapshot "$@"; }}
rollback_command_hint() {{ printf 'make deploy-rollback-%s' "$1"; }}
export PATH={shlex.quote(str(bin_dir))}:$PATH
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ bash -c "${{@: -1}}"; }}
ACX_DEPLOY_BACKUP_ROOT={shlex.quote(str(tmp_path / "backups"))}
ACX_DEPLOY_TRANSACTION_ID=transaction-a
{statements}
"""
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, env=os.environ.copy(), check=False)
    if records.exists():
        result.records = records.read_text(encoding="utf-8").splitlines()  # type: ignore[attr-defined]
    else:
        result.records = []  # type: ignore[attr-defined]
    return result


def _function_body(name: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n(.*?)^\}}", source)
    assert match, f"could not find function {name}"
    return match.group(1)


def _topology_restore_fixture(tmp_path: Path, *, pending: bool = False) -> dict:
    backup_root = tmp_path / "backups"
    current = backup_root / "dev" / "current-transaction"
    previous = backup_root / "dev" / "previous-transaction"
    edge_dir = tmp_path / "opt" / "acx-backend"
    (edge_dir / "app").mkdir(parents=True)
    (edge_dir / "docker-compose.caddy.yml").write_text("services: {}\n", encoding="utf-8")
    remote_dir = edge_dir / "dev"
    (remote_dir / "db/docker-prod-init").mkdir(parents=True)
    live_compose = remote_dir / "docker-compose.env.yml"
    live_compose.write_text("previous compose\n", encoding="utf-8")
    (remote_dir / "db/docker-prod-init/001-extensions.sql").write_text("previous sql\n", encoding="utf-8")
    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    (systemd_dir / "acx-dev.service").write_text("previous unit\n", encoding="utf-8")
    live_caddyfile = edge_dir / "Caddyfile"
    live_caddyfile.write_text("reverse_proxy dev-api:8000\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text(
        '''#!/usr/bin/env python3
import json, os, shlex, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
expected = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ConnectionAttempts=1",
            "-l", "fixture", "--", "fixture.invalid"]
if args[:-1] != expected:
    raise SystemExit("unexpected SSH transport")
prefix = "sudo timeout -k 5 20 bash -s -- "
if not args[-1].startswith(prefix):
    raise SystemExit("unexpected remote command")
action = args[-1][len(prefix):].split()[0]
program = sys.stdin.read()
def mapped(text):
    return text.replace("/opt/acx-backend", os.environ["FAKE_OPT"]).replace(
        "/etc/systemd/system", os.environ["FAKE_SYSTEMD"])
if action in ("restore-topology", "restore"):
    command = shlex.split(args[-1])
    Path(os.environ["CAPTURED_PAYLOAD"]).write_text(program)
    Path(os.environ["CAPTURED_ARGV"]).write_text(json.dumps(command[8:]))
    raise SystemExit(0)
if action not in ("acquire", "check", "snapshot", "command", "finish"):
    raise SystemExit("unexpected recognition edge action")
result = subprocess.run(["bash", "-c", mapped(args[-1])], input=mapped(program),
                        text=True, timeout=27)
raise SystemExit(result.returncode)
''',
        encoding="utf-8",
    )
    (bin_dir / "sudo").write_text(
        '#!/bin/sh\nexec "$@"\n',
        encoding="utf-8",
    )
    (bin_dir / "docker").write_text(
        '''#!/usr/bin/env python3
import json, sys
if sys.argv[1] != "compose" or sys.argv[-3:] != ["config", "--format", "json"]:
    raise SystemExit("unexpected Docker action")
print(json.dumps({"services": {"caddy": {"networks": {"dev": None}}},
                  "networks": {"dev": {"name": "acx-dev-net"}}}))
''',
        encoding="utf-8",
    )
    (bin_dir / "systemctl").write_text(
        '#!/bin/sh\n[ "$*" = daemon-reload ] || exit 98\nprintf "%s\\n" "$*" >>"$UNIT_RECORD"\n',
        encoding="utf-8",
    )
    for executable in bin_dir.iterdir():
        executable.chmod(0o755)
    payload = tmp_path / "restore.payload"
    arguments = tmp_path / "restore.argv.json"
    driver = f"""
set -euo pipefail
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
ACX_DEPLOY_BACKUP_ROOT="$BACKUP_ROOT"
ACX_DEPLOY_TRANSACTION_ID=previous-transaction
# Build complete topology, bootstrap, edge and generation evidence natively.
prepare_runtime_topology_backups dev 1
recognition_edge_finish
printf 'current compose\\n' >"$FAKE_REMOTE_DIR/docker-compose.env.yml"
printf 'current unit\\n' >"$FAKE_SYSTEMD/acx-dev.service"
printf 'current sql\\n' >"$FAKE_REMOTE_DIR/db/docker-prod-init/001-extensions.sql"
if [[ "${{RESTORE_STRICT:-1}}" == 1 ]]; then
  printf 'reverse_proxy dev-api-next:8000\\n' >"$FAKE_OPT/Caddyfile"
fi
ACX_DEPLOY_TRANSACTION_ID=current-transaction
recognition_edge_begin dev
if [[ "$PENDING_SNAPSHOT" == 1 ]]; then
  prepare_runtime_topology_backups dev 0
  # Interrupt a real snapshot at its readiness boundary.
  rm -- "$BACKUP_ROOT/dev/current-transaction/topology.ready"
  touch -- "$BACKUP_ROOT/dev/current-transaction/topology.pending"
  printf '%s\\n' "$BACKUP_ROOT/dev/previous-transaction" >"$BACKUP_ROOT/dev/latest"
fi
if [[ "${{RESTORE_STRICT:-1}}" == 1 ]]; then
  "$RESTORE_FUNCTION" dev current-only
else
  "$RESTORE_FUNCTION" dev
fi
"""
    env = os.environ.copy()
    env.update(
        {
            "BACKUP_ROOT": str(backup_root),
            "CAPTURED_PAYLOAD": str(payload),
            "CAPTURED_ARGV": str(arguments),
            "FAKE_REMOTE_DIR": str(remote_dir),
            "FAKE_SYSTEMD": str(systemd_dir),
            "FAKE_OPT": str(edge_dir),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "TMPDIR": str(tmp_path),
            "EDGE_LOCK_STATE_ROOT": str(tmp_path),
            "OCI_USER": "fixture",
            "OCI_HOST": "fixture.invalid",
            "APP_ROOT": "/opt/acx-backend/app",
            "ACX_REMOTE_COMMAND_TIMEOUT": "20",
            "ACX_EDGE_HANDLE": "",
            "ACX_EDGE_ENV": "",
            "PENDING_SNAPSHOT": str(int(pending)),
            "UNIT_RECORD": str(tmp_path / "systemctl.log"),
            "RESTORE_FUNCTION": "restore_topology_backups",
            "RESTORE_STRICT": "1",
        }
    )
    env.pop("AURA_EDGE_TEST_HELPER", None)
    env.pop("BASH_ENV", None)
    return {
        "backup_root": backup_root,
        "current": current,
        "previous": previous,
        "remote_dir": remote_dir,
        "live_compose": live_compose,
        "live_caddyfile": live_caddyfile,
        "systemd_dir": systemd_dir,
        "bin_dir": bin_dir,
        "payload": payload,
        "arguments": arguments,
        "driver": driver,
        "environment": env,
    }


def _restore_state(fixture: dict) -> dict:
    return {
        str(path): (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_ctime_ns, path.read_bytes())
        for root in (fixture["backup_root"], fixture["live_caddyfile"].parent, fixture["systemd_dir"])
        for path in root.rglob("*") if path.is_file()
    }


def _capture_and_run_restore(
    tmp_path: Path, *, function: str, strict: bool, pending: bool = False
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str], dict]:
    fixture = _topology_restore_fixture(tmp_path, pending=pending)
    env = fixture["environment"].copy()
    env["RESTORE_FUNCTION"] = function
    if not strict:
        env["RESTORE_STRICT"] = "0"
    try:
        capture = subprocess.run(
            ["bash", "-c", fixture["driver"]], text=True, capture_output=True, check=False, env=env, timeout=55
        )
        assert capture.returncode == 0, capture.stdout + capture.stderr
        program = subprocess.run(
            ["bash", "-c", f"source {shlex.quote(str(SCRIPT))}; recognition_edge_program"],
            text=True, capture_output=True, check=True, env=env, timeout=5,
        ).stdout
        # Command substitution strips trailing newlines; the transport adds one.
        assert fixture["payload"].read_text() == program.rstrip("\n") + "\n"
        argv = json.loads(fixture["arguments"].read_text())
        assert argv[:2] == ["restore-topology" if function == "restore_topology_backups" else "restore",
                            "/opt/acx-backend/app"]
        assert argv[3:] == ["20", "dev", "current-transaction", str(fixture["backup_root"]),
                            "current-only" if strict else ""]
        assert Path(argv[2]).is_dir(), "native ownership handle must exist"
        def mapped(text: str) -> str:
            return text.replace("/opt/acx-backend", env["FAKE_OPT"]).replace(
                "/etc/systemd/system", env["FAKE_SYSTEMD"]
            )
        executable = tmp_path / "restore.mapped.payload"
        executable.write_text(mapped(fixture["payload"].read_text()), encoding="utf-8")
        fixture["before_state"] = _restore_state(fixture)
        execute = subprocess.run(
            ["bash", str(executable), *(mapped(arg) for arg in argv)],
            text=True, capture_output=True, check=False, env=env, cwd=tmp_path, timeout=27,
        )
        fixture["after_state"] = _restore_state(fixture)
    finally:
        for handle in tmp_path.glob("shared-edge-lock.*"):
            cleanup = subprocess.run(
                ["bash", "-c", 'source "$1"; edge_lock_release "$2" 2', "_",
                 str(SCRIPT.parent / "lib/shared-edge.sh"), str(handle)],
                env=env, text=True, capture_output=True, timeout=5,
            )
            assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr
    return capture, execute, fixture


def _assert_no_restore_writes(fixture: dict) -> None:
    # Includes live files, all snapshots/pointers, and the native owner journal.
    assert fixture["after_state"] == fixture["before_state"]
    assert not Path(fixture["environment"]["UNIT_RECORD"]).exists()


def test_interrupt_after_repo_ship_restores_topology_and_repo(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_runtime_topology dev current-only") < records.index("restore_prior_image_repo_env")
    assert records.index("restore_prior_image_repo_env") < records.index("_purge_deploy_ocir_docker_config")


def test_repo_shipped_interrupt_uses_strict_topology_restore(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_runtime_topology dev current-only" in records


def test_repo_shipped_current_only_does_not_abort_candidate(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r"""
restore_topology_backups() { record restore_topology_backups "$@"; }
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130
""",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_topology_backups dev current-only" in records
    assert "restore_edge_backups dev current-only" in records
    assert not any(record.startswith("abort_cutover_candidate") for record in records)


def test_non_strict_topology_restore_still_aborts_candidate(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r"""
restore_topology_backups() { record restore_topology_backups "$@"; }
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
restore_runtime_topology dev
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_topology_backups dev" in records
    assert "restore_edge_backups dev" in records
    assert "abort_cutover_candidate dev" in records


@pytest.mark.parametrize("restore_mode", ["current-only", ""])
@pytest.mark.parametrize("admission_rc", [0, 75], ids=["admitted", "refused"])
def test_runtime_restore_admission_precedes_every_writer(
    tmp_path: Path, restore_mode: str, admission_rc: int
) -> None:
    result = _run_real_driver(
        tmp_path,
        r"""
recognition_edge_assert_if_active() { record ownership; }
restore_topology_backups() { record restore_topology_backups "$@"; }
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
"""
        + f"\nFIXTURE_ADMISSION_RC={admission_rc}\nrestore_runtime_topology dev {shlex.quote(restore_mode)}\n",
    )
    assert result.returncode == admission_rc, result.stdout + result.stderr
    expected = ["ownership", f"recognition_edge_remote admit-runtime dev {shlex.quote(restore_mode)}"]
    if admission_rc == 0:
        suffix = f" {restore_mode}" if restore_mode else ""
        expected += [f"restore_topology_backups dev{suffix}", f"restore_edge_backups dev{suffix}"]
        if not restore_mode:
            expected.append("abort_cutover_candidate dev")
    assert result.records == expected  # type: ignore[attr-defined]


def test_repo_shipped_admission_refusal_skips_topology_writers(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r"""
restore_topology_backups() { record restore_topology_backups "$@"; }
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
restore_prior_image_repo_env() { record restore_prior_image_repo_env "$@"; }
FIXTURE_ADMISSION_RC=75
ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130
""",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    assert result.records == [  # type: ignore[attr-defined]
        "cleanup_remote_build_generation_on_exit",
        "recognition_edge_remote admit-runtime dev current-only",
        "restore_prior_image_repo_env",
        "_purge_deploy_ocir_docker_config",
        "_purge_deploy_snapshot",
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        "restore dev current-only",
        "admit-runtime dev",
        "admit-runtime dev current-only extra",
        "admit-runtime staging current-only",
        "admit-runtime dev unknown-mode",
    ],
)
def test_compensation_admission_double_refuses_unmodeled_calls(tmp_path: Path, arguments: str) -> None:
    result = _run_real_driver(tmp_path, f"recognition_edge_remote {arguments}\n")
    assert result.returncode == 97, result.stdout + result.stderr
    assert "unmodeled compensation admission call" in result.stderr
    assert result.records == [f"recognition_edge_remote {arguments}"]  # type: ignore[attr-defined]


def test_interrupt_during_canonical_restart_leaves_candidate_serving(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r"""
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
commit_cutover_state() { record commit_cutover_state "$@"; }
ACX_CUTOVER_ENV=dev ACX_TRAFFIC_FLIPPED=1 ACX_LIVE_DISRUPTED=1; deploy_interrupt_cleanup 130
""",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert not any(
        record.startswith(("restore_edge_backups", "abort_cutover_candidate", "commit_cutover_state"))
        for record in records
    )
    assert "make deploy-rollback-dev" in result.stderr
    assert "traffic left on dev-next" in result.stderr


def test_interrupt_after_flip_before_restart_still_recovers(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r"""
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
commit_cutover_state() { record commit_cutover_state "$@"; }
ACX_CUTOVER_ENV=dev ACX_TRAFFIC_FLIPPED=1 ACX_LIVE_DISRUPTED=0; deploy_interrupt_cleanup 130
""",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_edge_backups dev") < records.index("abort_cutover_candidate dev")
    assert records.index("abort_cutover_candidate dev") < records.index("commit_cutover_state dev")


def test_strict_restore_ignores_latest_pointer(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(tmp_path, function="restore_topology_backups", strict=True)
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 0, execute.stdout + execute.stderr
    assert fixture["live_compose"].read_text(encoding="utf-8") == "current compose\n"
    assert execute.stdout == execute.stderr == ""
    _assert_no_restore_writes(fixture)


def test_strict_edge_restore_ignores_latest_and_cutover_pointer(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(tmp_path, function="restore_edge_backups", strict=True)
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 0, execute.stdout + execute.stderr
    assert fixture["live_caddyfile"].read_text(encoding="utf-8") == "reverse_proxy dev-api-next:8000\n"
    assert execute.stdout == execute.stderr == ""
    _assert_no_restore_writes(fixture)


def test_non_strict_restore_still_uses_latest(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(tmp_path, function="restore_topology_backups", strict=False)
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 0, execute.stdout + execute.stderr
    assert fixture["live_compose"].read_text(encoding="utf-8") == "previous compose\n"
    assert (fixture["systemd_dir"] / "acx-dev.service").read_text() == "previous unit\n"
    bootstrap = fixture["remote_dir"] / "db/docker-prod-init/001-extensions.sql"
    assert bootstrap.read_bytes() == b"previous sql\n"
    restored = {str(fixture["live_compose"]), str(fixture["systemd_dir"] / "acx-dev.service"), str(bootstrap)}
    before, after = fixture["before_state"], fixture["after_state"]
    assert before.keys() == after.keys()
    assert {path for path in before if before[path] != after[path]} == restored
    for path in restored:
        assert before[path][0] == after[path][0], "restore must preserve the live bind inode"
        assert before[path][-1] != after[path][-1], "restore must actually replace current bytes"
    assert Path(fixture["environment"]["UNIT_RECORD"]).read_text() == "daemon-reload\n"
    assert execute.stdout == execute.stderr == ""


def test_strict_restore_refuses_incomplete_current_snapshot(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(
        tmp_path, function="restore_topology_backups", strict=True, pending=True
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 2, execute.stdout + execute.stderr
    assert execute.stderr == "topology restore admission refused: topology snapshot is incomplete\n"
    assert execute.stdout == ""
    _assert_no_restore_writes(fixture)


def test_interrupt_after_tag_push_restores_env_tag(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_env_tag_to_rollback dev 0") < records.index("restore_prior_image_repo_env")
    assert records.index("restore_prior_image_repo_env") < records.index("_purge_deploy_ocir_docker_config")

    refused = _run_driver(
        tmp_path / "owner-refused",
        "ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130",
        RESTORE_ENV_RC="75",
    )
    assert refused.returncode == 130, refused.stdout + refused.stderr
    refused_records = refused.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" in refused_records
    assert "restore_prior_image_repo_env" not in refused_records


def test_interrupt_after_live_disruption_only_warns(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted ACX_LIVE_DISRUPTED=1; deploy_interrupt_cleanup 130",
    )
    assert result.returncode == 130, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "not rolling back from a signal handler" in output
    records = result.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" not in records
    assert "_purge_deploy_ocir_docker_config" in records


def test_interrupted_compensation_skips_when_lease_is_lost(tmp_path: Path) -> None:
    for phase in ("tag_promoted", "repo_shipped"):
        case_dir = tmp_path / phase
        lease_path = case_dir / "backups" / "locks" / "deploy-dev.lease"
        original = _write_lease(
            lease_path,
            "transaction-b",
            "other@example:456",
            int(time.time()) + 3600,
        )
        result = _run_lease_driver(
            case_dir,
            f"ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE={phase} ACX_DEPLOY_LEASE_ENV=dev; deploy_interrupt_cleanup 130",
        )

        assert result.returncode == 130, result.stdout + result.stderr
        output = result.stdout + result.stderr
        assert "lost to other@example:456" in output
        assert "skipping compensation" in output
        records = result.records  # type: ignore[attr-defined]
        assert "restore_prior_image_repo_env" not in records
        if phase == "tag_promoted":
            assert "restore_env_tag_to_rollback dev 0" not in records
        else:
            assert "restore_runtime_topology dev current-only" not in records
        assert lease_path.read_bytes() == original


def test_interrupted_compensation_runs_when_lease_is_owned(tmp_path: Path) -> None:
    result = _run_lease_driver(
        tmp_path,
        "deploy_env_lease acquire dev; ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130",
    )

    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" in records
    assert "restore_prior_image_repo_env" in records


def test_failed_verification_skips_evidence_and_rollback_after_lease_loss(
    tmp_path: Path,
) -> None:
    lease_path = tmp_path / "backups" / "locks" / "deploy-dev.lease"
    original = _write_lease(
        lease_path,
        "transaction-b",
        "other@example:456",
        int(time.time()) + 3600,
    )
    evidence_marker = tmp_path / "evidence-captured"
    rollback_marker = tmp_path / "rollback-ran"
    result = _run_lease_driver(
        tmp_path,
        f"""
capture_failure_evidence() {{ touch {shlex.quote(str(evidence_marker))}; }}
restore_env_tag_to_rollback() {{ touch {shlex.quote(str(rollback_marker))}; }}
ACX_DEPLOY_LEASE_ENV=dev
handle_failed_verification dev Deploy
""",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert not evidence_marker.exists()
    assert not rollback_marker.exists()
    assert lease_path.read_bytes() == original


def test_failed_verification_rolls_back_when_lease_is_owned(tmp_path: Path) -> None:
    evidence_marker = tmp_path / "evidence-captured"
    rollback_marker = tmp_path / "rollback-ran"
    result = _run_lease_driver(
        tmp_path,
        f"""
deploy_env_lease acquire dev
capture_failure_evidence() {{ touch {shlex.quote(str(evidence_marker))}; }}
restore_env_tag_to_rollback() {{ touch {shlex.quote(str(rollback_marker))}; }}
handle_failed_verification dev Deploy
""",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert evidence_marker.exists()
    assert rollback_marker.exists()


def test_no_phase_is_a_noop(tmp_path: Path) -> None:
    result = _run_driver(tmp_path, 'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=""; deploy_interrupt_cleanup 130')
    assert result.returncode == 130, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "compensating" not in output
    records = result.records  # type: ignore[attr-defined]
    assert not any(name.startswith("restore_") for name in records)
    assert "_purge_deploy_ocir_docker_config" in records


def test_restarted_and_compensating_only_warn(tmp_path: Path) -> None:
    for phase, warning in (
        ("restarted", "serves unverified"),
        ("compensating", "during rollback"),
    ):
        result = _run_driver(
            tmp_path / phase,
            f"ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE={phase} ACX_CANDIDATE_DIGEST_REF=repo@sha256:abc; deploy_interrupt_cleanup 130",
        )
        assert result.returncode == 130, result.stdout + result.stderr
        assert warning in result.stdout + result.stderr
        records = result.records  # type: ignore[attr-defined]
        assert not any(name.startswith("restore_") for name in records)
        assert "_purge_deploy_ocir_docker_config" in records


def test_compensation_runs_once(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup; trap deploy_interrupt_cleanup EXIT",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.count("restore_env_tag_to_rollback dev 0") == 1


def test_ship_interrupt_between_push_and_restart(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        r"""
pin_deploy_sha() { DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
init_deploy_ocir_docker_config() { install_deploy_interrupt_traps; }
preflight_ssh() { :; }
deploy_env_lease() { return 0; }
preflight_remote_face_pipeline_models() { :; }
preflight_git_clean() { :; }
preflight_branch_synced() { :; }
preflight_remote_ocir_auth() { :; }
preserve_rollback_tag() { :; }
capture_prior_runtime_identity() { :; }
do_build() { :; }
do_push_sha() { ACX_CANDIDATE_DIGEST_REF=repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
promote_gate() { ACX_DEPLOY_PHASE=repo_shipped; }
do_push_tag() { record do_push_tag "$@"; kill -INT "$$"; }
do_restart() { record do_restart "$@"; }
_ship_selected_env dev aggregate
""",
    )
    output = result.stdout + result.stderr
    assert "Deploy submitted. Verifying..." not in output, output
    assert result.returncode == 130, output
    records = result.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" in records
    assert "do_restart dev repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in records


def test_ship_tag_push_failure_skips_rollback_after_lease_loss(tmp_path: Path) -> None:
    lease_path = tmp_path / "backups" / "locks" / "deploy-dev.lease"
    rollback_marker = tmp_path / "rollback-marker"
    repo_marker = tmp_path / "repo-restore-marker"
    foreign_lease = json.dumps(
        {
            "transaction": "transaction-b",
            "holder": "other@example:789",
            "expires_at": 4102444800,
        },
        separators=(",", ":"),
    )
    statements = f"""
pin_deploy_sha() {{ DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
init_deploy_ocir_docker_config() {{ install_deploy_interrupt_traps; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preserve_rollback_tag() {{ :; }}
capture_prior_runtime_identity() {{ :; }}
do_build() {{ :; }}
do_push_sha() {{ ACX_CANDIDATE_DIGEST_REF=repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
promote_gate() {{ ACX_DEPLOY_PHASE=repo_shipped; }}
do_push_tag() {{ printf '%s' {shlex.quote(foreign_lease)} >{shlex.quote(str(lease_path))}; return 1; }}
capture_failure_evidence() {{ :; }}
restore_env_tag_to_rollback() {{ touch {shlex.quote(str(rollback_marker))}; }}
restore_prior_image_repo_env() {{ touch {shlex.quote(str(repo_marker))}; }}
_ship_selected_env dev aggregate
"""
    result = _run_lease_driver(tmp_path, statements)

    assert result.returncode != 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "lost to other@example:789" in output
    assert "skipping compensation" in output
    assert not rollback_marker.exists()
    assert not repo_marker.exists()
    assert lease_path.read_text(encoding="ascii") == foreign_lease


def test_phase_boundaries_are_recorded() -> None:
    gate = _function_body("promote_gate")
    claim = gate.index('ACX_IMAGE_REPO_OWNER_ID="$(image_repo_resource claim')
    assert gate.index("ACX_DEPLOY_PHASE=repo_shipped") < claim

    for name in ("_ship_selected_env", "do_promote"):
        body = _function_body(name)
        push = body.index("if do_push_tag")
        assert body.index("ACX_DEPLOY_PHASE=tag_promoted", push) > push
