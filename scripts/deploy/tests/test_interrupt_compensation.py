"""Regressions for deploy state left behind when an interrupted transaction exits."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"


def _run_driver(tmp_path: Path, statements: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = tmp_path / "records.log"
    command = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
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
'''
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
    command = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
deploy_env_lease() {{ return 0; }}
cleanup_remote_build_generation_on_exit() {{ record cleanup_remote_build_generation_on_exit "$@"; }}
_purge_deploy_ocir_docker_config() {{ record _purge_deploy_ocir_docker_config "$@"; }}
_purge_deploy_snapshot() {{ record _purge_deploy_snapshot "$@"; }}
rollback_command_hint() {{ printf 'make deploy-rollback-%s' "$1"; }}
{statements}
'''
    result = subprocess.run(
        ["bash", "-c", command], text=True, capture_output=True, env=os.environ.copy(), check=False
    )
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
    command = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
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
'''
    result = subprocess.run(
        ["bash", "-c", command], text=True, capture_output=True, env=os.environ.copy(), check=False
    )
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


def _topology_restore_fixture(tmp_path: Path, *, pending: bool = False) -> dict[str, Path]:
    backup_root = tmp_path / "backups"
    current = backup_root / "dev" / "current-transaction"
    previous = backup_root / "dev" / "previous-transaction"
    current.mkdir(parents=True)
    if pending:
        (current / "topology.pending").touch()
    previous.mkdir(parents=True)
    (previous / "topology.ready").touch()
    (backup_root / "dev" / "latest").write_text(f"{previous}\n", encoding="utf-8")
    (previous / "docker-compose.env.yml").write_text("previous compose\n", encoding="utf-8")
    (previous / "acx-dev.service").write_text("previous unit\n", encoding="utf-8")
    (previous / "edge").mkdir()
    (previous / "edge" / "Caddyfile.pre-cutover").write_text(
        "reverse_proxy dev-api:8000\n", encoding="utf-8"
    )
    (backup_root / "dev" / "edge-cutover.current").write_text(
        f"{previous}/edge/Caddyfile.pre-cutover\n", encoding="utf-8"
    )

    remote_dir = tmp_path / "remote" / "dev"
    remote_dir.mkdir(parents=True)
    live_compose = remote_dir / "docker-compose.env.yml"
    live_compose.write_text("current compose\n", encoding="utf-8")
    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    (systemd_dir / "acx-dev.service").write_text("current unit\n", encoding="utf-8")
    edge_dir = tmp_path / "opt" / "acx-backend"
    edge_dir.mkdir(parents=True)
    live_caddyfile = edge_dir / "Caddyfile"
    live_caddyfile.write_text("reverse_proxy dev-api-next:8000\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        "last=\n"
        "for arg in \"$@\"; do last=$arg; done\n"
        "if [[ $last == 'bash -s' ]]; then cat >\"$CAPTURED_PAYLOAD\"; "
        "else printf '%s\\n' \"$last\" >\"$CAPTURED_PAYLOAD\"; fi\n",
        encoding="utf-8",
    )
    (bin_dir / "sudo").write_text(
        "#!/usr/bin/env bash\n"
        "args=()\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    /etc/systemd/system/*) args+=(\"$FAKE_SYSTEMD/${arg#/etc/systemd/system/}\") ;;\n"
        "    /opt/acx-backend/*) args+=(\"$FAKE_OPT/${arg#/opt/acx-backend/}\") ;;\n"
        "    *) args+=(\"$arg\") ;;\n"
        "  esac\n"
        "done\n"
        "if [[ ${args[0]:-} == systemctl ]]; then exit 0; fi\n"
        "exec \"${args[@]}\"\n",
        encoding="utf-8",
    )
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *'ps -q caddy'* ]]; then printf 'cid\\n'; "
        "elif [[ \"$1 $2\" == 'inspect -f' ]]; then "
        "printf '{\"acx-prod-net\":{},\"acx-staging-net\":{},\"acx-dev-net\":{},'"
        "'\"acx-dev-fir-net\":{},\"acx-demo-net\":{}}\\n'; fi\n",
        encoding="utf-8",
    )
    bash_env = tmp_path / "bash-env"
    bash_env.write_text(
        "cd() { if [[ ${1:-} == /opt/acx-backend ]]; then "
        "builtin cd \"$FAKE_OPT\"; else builtin cd \"$@\"; fi; }\n",
        encoding="utf-8",
    )
    (bin_dir / "ssh").chmod(0o755)
    (bin_dir / "sudo").chmod(0o755)
    (bin_dir / "docker").chmod(0o755)
    payload = tmp_path / "restore.payload"
    driver = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
run_with_deadline() {{ shift 2; "$@"; }}
env_to_remote_dir() {{ printf '%s\\n' "$FAKE_REMOTE_DIR"; }}
ACX_DEPLOY_BACKUP_ROOT="$BACKUP_ROOT"
ACX_DEPLOY_TRANSACTION_ID=current-transaction
if [[ "${{RESTORE_STRICT:-1}}" == 1 ]]; then
  "$RESTORE_FUNCTION" dev current-only
else
  "$RESTORE_FUNCTION" dev
fi
'''
    env = os.environ.copy()
    env.update(
        {
            "BACKUP_ROOT": str(backup_root),
            "CAPTURED_PAYLOAD": str(payload),
            "FAKE_REMOTE_DIR": str(remote_dir),
            "FAKE_SYSTEMD": str(systemd_dir),
            "FAKE_OPT": str(edge_dir),
            "BASH_ENV": str(bash_env),
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "RESTORE_FUNCTION": "restore_topology_backups",
        }
    )
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
        "driver": Path(driver),
        "environment": env,
    }


def _capture_and_run_restore(
    tmp_path: Path, *, function: str, strict: bool, pending: bool = False
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str], dict[str, Path]]:
    fixture = _topology_restore_fixture(tmp_path, pending=pending)
    env = fixture["environment"].copy()
    env["RESTORE_FUNCTION"] = function
    if not strict:
        env["RESTORE_STRICT"] = "0"
    env["PATH"] = f"{fixture['bin_dir']}:{env.get('PATH', '')}"
    driver = str(fixture["driver"])
    capture = subprocess.run(
        ["bash", "-c", driver], text=True, capture_output=True, check=False, env=env
    )
    assert fixture["payload"].exists(), capture.stdout + capture.stderr
    execute = subprocess.run(
        ["bash", str(fixture["payload"])],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=tmp_path,
    )
    return capture, execute, fixture


def test_interrupt_after_repo_ship_restores_topology_and_repo(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_runtime_topology dev current-only") < records.index("restore_prior_image_repo_env")
    assert records.index("restore_prior_image_repo_env") < records.index("_purge_deploy_ocir_docker_config")


def test_repo_shipped_interrupt_uses_strict_topology_restore(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_runtime_topology dev current-only" in records


def test_repo_shipped_current_only_does_not_abort_candidate(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r'''
restore_topology_backups() { record restore_topology_backups "$@"; }
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130
''',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_topology_backups dev current-only" in records
    assert "restore_edge_backups dev current-only" in records
    assert not any(record.startswith("abort_cutover_candidate") for record in records)


def test_non_strict_topology_restore_still_aborts_candidate(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r'''
restore_topology_backups() { record restore_topology_backups "$@"; }
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
restore_runtime_topology dev
''',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_topology_backups dev" in records
    assert "restore_edge_backups dev" in records
    assert "abort_cutover_candidate dev" in records


def test_interrupt_during_canonical_restart_leaves_candidate_serving(tmp_path: Path) -> None:
    result = _run_real_driver(
        tmp_path,
        r'''
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
commit_cutover_state() { record commit_cutover_state "$@"; }
ACX_CUTOVER_ENV=dev ACX_TRAFFIC_FLIPPED=1 ACX_LIVE_DISRUPTED=1; deploy_interrupt_cleanup 130
''',
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
        r'''
restore_edge_backups() { record restore_edge_backups "$@"; }
abort_cutover_candidate() { record abort_cutover_candidate "$@"; }
commit_cutover_state() { record commit_cutover_state "$@"; }
ACX_CUTOVER_ENV=dev ACX_TRAFFIC_FLIPPED=1 ACX_LIVE_DISRUPTED=0; deploy_interrupt_cleanup 130
''',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_edge_backups dev") < records.index("abort_cutover_candidate dev")
    assert records.index("abort_cutover_candidate dev") < records.index("commit_cutover_state dev")


def test_strict_restore_ignores_latest_pointer(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(
        tmp_path, function="restore_topology_backups", strict=True
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 0, execute.stdout + execute.stderr
    assert fixture["live_compose"].read_text(encoding="utf-8") == "current compose\n"
    assert "no current-transaction topology snapshot; topology left untouched" in execute.stdout


def test_strict_edge_restore_ignores_latest_and_cutover_pointer(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(
        tmp_path, function="restore_edge_backups", strict=True
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 0, execute.stdout + execute.stderr
    assert fixture["live_caddyfile"].read_text(encoding="utf-8") == "reverse_proxy dev-api-next:8000\n"
    assert "no current-transaction topology snapshot; topology left untouched" in execute.stdout


def test_non_strict_restore_still_uses_latest(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(
        tmp_path, function="restore_topology_backups", strict=False
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 0, execute.stdout + execute.stderr
    assert fixture["live_compose"].read_text(encoding="utf-8") == "previous compose\n"


def test_strict_restore_refuses_incomplete_current_snapshot(tmp_path: Path) -> None:
    capture, execute, fixture = _capture_and_run_restore(
        tmp_path, function="restore_topology_backups", strict=True, pending=True
    )
    assert capture.returncode == 0, capture.stdout + capture.stderr
    assert execute.returncode == 1
    assert "topology snapshot is incomplete; refusing restore" in execute.stderr


def test_interrupt_after_tag_push_restores_env_tag(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_env_tag_to_rollback dev 0") < records.index("restore_prior_image_repo_env")
    assert records.index("restore_prior_image_repo_env") < records.index("_purge_deploy_ocir_docker_config")

    refused = _run_driver(
        tmp_path / "owner-refused",
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130',
        RESTORE_ENV_RC="75",
    )
    assert refused.returncode == 130, refused.stdout + refused.stderr
    refused_records = refused.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" in refused_records
    assert "restore_prior_image_repo_env" not in refused_records


def test_interrupt_after_live_disruption_only_warns(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted ACX_LIVE_DISRUPTED=1; deploy_interrupt_cleanup 130',
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
            f'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE={phase} ACX_DEPLOY_LEASE_ENV=dev; deploy_interrupt_cleanup 130',
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
        'deploy_env_lease acquire dev; ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130',
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
        f'''
capture_failure_evidence() {{ touch {shlex.quote(str(evidence_marker))}; }}
restore_env_tag_to_rollback() {{ touch {shlex.quote(str(rollback_marker))}; }}
ACX_DEPLOY_LEASE_ENV=dev
handle_failed_verification dev Deploy
''',
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
        f'''
deploy_env_lease acquire dev
capture_failure_evidence() {{ touch {shlex.quote(str(evidence_marker))}; }}
restore_env_tag_to_rollback() {{ touch {shlex.quote(str(rollback_marker))}; }}
handle_failed_verification dev Deploy
''',
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
            f'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE={phase} ACX_CANDIDATE_DIGEST_REF=repo@sha256:abc; deploy_interrupt_cleanup 130',
        )
        assert result.returncode == 130, result.stdout + result.stderr
        assert warning in result.stdout + result.stderr
        records = result.records  # type: ignore[attr-defined]
        assert not any(name.startswith("restore_") for name in records)
        assert "_purge_deploy_ocir_docker_config" in records


def test_compensation_runs_once(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup; trap deploy_interrupt_cleanup EXIT',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.count("restore_env_tag_to_rollback dev 0") == 1


def test_ship_interrupt_between_push_and_restart(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        r'''
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
''',
    )
    assert result.returncode == 130, result.stdout + result.stderr
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
    statements = f'''
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
'''
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
